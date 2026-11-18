"""GitHub App REST adapter. Reads are GET; writes are the allowlisted PR open and merge calls only. No credential-bearing redirects or URLs."""
import json
import math
from contextvars import ContextVar
import os
from pathlib import Path
import re
import time
from urllib.parse import quote, urlencode, urlsplit

from .errors import AccessDenied, ValidationError
from .git_workspace import branch_name


_operation = ContextVar('github_rest_operation',default=None)


class GitHubError(Exception):
    def __init__(self, message='GitHub request failed', *, retryable=False,retry_after=0,rate_limited=False):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = min(86400,max(0,math.ceil(retry_after)))
        self.rate_limited = rate_limited


class GitHubAccessDenied(AccessDenied):
    def __init__(self,status):
        super().__init__('GitHub repository access not accepted')
        self.status=status


def positive_id(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise ValidationError('Expected a positive GitHub identifier')
    return value


def complete_sha(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',value):
        raise ValidationError('Expected a complete commit SHA')
    return value


class GitHubApp:
    API_VERSION = '2026-03-10'
    MAX_RESPONSE = 2_000_000
    MAX_OPERATION_REQUESTS = 150
    OPERATION_SECONDS = 60
    DISCOVERY_LIMIT = 50
    RELEASE_DISCOVERY_LIMIT = 20
    RELEASE_ASSET_LIMIT = 20
    CHECK_LIMIT = 100
    def __init__(self, app_id=None, client_id=None, client_secret=None, private_key=None,
                 webhook_secret=None, callback_url=None):
        self.enabled = any(v is not None for v in (app_id,client_id,client_secret,private_key,webhook_secret,callback_url))
        self._client = None
        self.webhook_secret = webhook_secret
        if not self.enabled:
            return
        if not all(isinstance(v,str) and v and len(v)<=65536 for v in
                   (app_id,client_id,client_secret,private_key,webhook_secret,callback_url)):
            raise ValidationError('GitHub App configuration is incomplete or invalid')
        if not re.fullmatch(r'[1-9][0-9]{0,18}',app_id) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',client_id):
            raise ValidationError('GitHub App identifiers are invalid')
        parsed=urlsplit(callback_url)
        if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path!='/api/git/github/callback'):
            raise ValidationError('GitHub callback requires a public HTTPS callback URL')
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
            key=load_pem_private_key(private_key.encode(),password=None)
            if not isinstance(key,RSAPrivateKey) or key.key_size<2048:
                raise ValueError()
        except (ValueError,TypeError):
            raise ValidationError('GitHub App requires a valid RSA private key') from None
        self.app_id,self.client_id,self.client_secret,self.private_key,self.callback_url=app_id,client_id,client_secret,private_key,callback_url

    @classmethod
    def from_env(cls, public_origin=None):
        def setting(name,secret=False):
            value=os.environ.get('COOPAGENTS_GITHUB_'+name)
            filename=os.environ.get('COOPAGENTS_GITHUB_'+name+'_FILE') if secret else None
            if value is not None and filename is not None:
                raise ValidationError('Use exactly one GitHub secret source')
            if filename is not None:
                try:
                    with Path(filename).open('rb') as f:
                        raw=f.read(65537)
                    if len(raw)>65536: raise ValueError()
                    value=raw.decode('utf-8').strip()
                except (OSError,UnicodeError,ValueError):
                    raise ValidationError('GitHub secret file cannot be read') from None
            return value
        values=[setting('APP_ID'),setting('APP_CLIENT_ID'),setting('APP_CLIENT_SECRET',True),
                setting('APP_PRIVATE_KEY',True),setting('WEBHOOK_SECRET',True)]
        callback=setting('APP_CALLBACK_URL')
        if not any(v is not None for v in values+[callback]):
            return cls()
        if callback is None and public_origin:
            callback=public_origin.rstrip('/')+'/api/git/github/callback'
        return cls(*values,callback)

    def jwt(self):
        if not self.enabled: raise AccessDenied('GitHub App is not configured')
        import jwt
        current=int(time.time())
        return jwt.encode({'iat':current-60,'exp':current+540,'iss':self.app_id},self.private_key,algorithm='RS256')

    @staticmethod
    def _rate_delay(headers):
        delay=60
        after=headers.get('retry-after','')
        reset=headers.get('x-ratelimit-reset','')
        if re.fullmatch(r'[0-9]{1,12}',after): delay=int(after)
        elif headers.get('x-ratelimit-remaining')=='0' and re.fullmatch(r'[0-9]{1,12}',reset):
            delay=math.ceil(int(reset)-time.time())
        return min(86400,max(60,delay))

    def _request_url(self,method,url,token=None,data=None):
        import httpx2 as httpx
        operation=_operation.get()
        timeout=15
        if operation is not None:
            remaining=operation['deadline']-time.monotonic()
            if remaining<=0 or operation['requests']>=self.MAX_OPERATION_REQUESTS:
                raise GitHubError('GitHub synchronization operation exceeds budget',retryable=True)
            operation['requests']+=1
            timeout=min(timeout,remaining)
        headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':self.API_VERSION,
                 'User-Agent':'Coopagents-GitHub-App'}
        if url=='https://github.com/login/oauth/access_token': headers['Accept']='application/json'
        if token: headers['Authorization']='Bearer '+token
        try:
            client=self._client or httpx.Client(timeout=15,follow_redirects=False,trust_env=False)
            try:
                with client.stream(method,url,headers=headers,json=data,timeout=timeout,follow_redirects=False) as response:
                    content=bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content)>self.MAX_RESPONSE: raise GitHubError('GitHub response exceeds limit')
                        if operation is not None and time.monotonic()>operation['deadline']:
                            raise GitHubError('GitHub synchronization operation exceeds budget',retryable=True)
                    try: result=json.loads(content)
                    except (ValueError,UnicodeError): result=None
                    if response.status_code in (403,429):
                        message=result.get('message','') if isinstance(result,dict) else ''
                        secondary=isinstance(message,str) and any(marker in message.lower() for marker in ('rate limit','abuse detection'))
                        throttled=(response.status_code==429 or secondary or response.headers.get('x-ratelimit-remaining')=='0' or 'retry-after' in response.headers)
                        if throttled:
                            raise GitHubError('GitHub rate limited',retryable=True,
                                retry_after=self._rate_delay(response.headers),rate_limited=True)
                        raise GitHubAccessDenied(response.status_code)
                    if response.status_code in (401,404): raise GitHubAccessDenied(response.status_code)
                    if response.status_code<200 or response.status_code>=300:
                        raise GitHubError(retryable=response.status_code>=500)
                    if not isinstance(result,(dict,list)): raise GitHubError('GitHub response is invalid')
                    return result
            finally:
                if self._client is None: client.close()
        except AccessDenied:
            raise
        except (httpx.HTTPError,OSError):
            raise GitHubError('GitHub temporarily unavailable',retryable=True) from None
        except (ValueError,UnicodeError):
            raise GitHubError('GitHub response is invalid') from None

    def request(self,method,path,token,data=None):
        if (not isinstance(path,str) or not path.startswith('/') or path.startswith('//')
                or '#' in path or any(ord(x)<32 for x in path) or '\\' in path or len(path)>2000
                or (method not in ('GET','POST')
                    and not (method=='PUT' and re.fullmatch(r'/repos/[^/]+/[^/]+/pulls/[0-9]+/merge',path)))):
            raise ValidationError('Unsupported GitHub API request')
        return self._request_url(method,'https://api.github.com'+path,token,data)

    def pages(self,path,token,key=None):
        result=[]
        for page in range(1,101):
            body=self.request('GET',path+('&' if '?' in path else '?')+urlencode({'per_page':100,'page':page}),token)
            batch=body.get(key) if key and isinstance(body,dict) else body
            if not isinstance(batch,list) or len(batch)>100: raise GitHubError('GitHub pagination is invalid')
            result.extend(batch)
            if len(batch)<100: return result
        raise GitHubError('GitHub pagination exceeds limit')

    def bounded_page(self,path,token,key=None,limit=100):
        body=self.request('GET',path+('&' if '?' in path else '?')+urlencode({'per_page':limit,'page':1}),token)
        batch=body.get(key) if key and isinstance(body,dict) else body
        if not isinstance(batch,list) or len(batch)>limit: raise GitHubError('GitHub page exceeds limit')
        total=body.get('total_count') if isinstance(body,dict) else None
        truncated=(type(total) is int and total>limit) or len(batch)==limit
        return batch,truncated

    def authorization_url(self,state):
        if not self.enabled: raise AccessDenied('GitHub App is not configured')
        return 'https://github.com/login/oauth/authorize?'+urlencode({'client_id':self.client_id,'redirect_uri':self.callback_url,'state':state})

    def exchange_code(self,code):
        if not isinstance(code,str) or not 1<=len(code)<=1000 or any(ord(x)<32 for x in code):
            raise ValidationError('OAuth code is invalid')
        result=self._request_url('POST','https://github.com/login/oauth/access_token',data={
            'client_id':self.client_id,'client_secret':self.client_secret,'code':code,'redirect_uri':self.callback_url})
        token=result.get('access_token') if isinstance(result,dict) else None
        if not isinstance(token,str) or not 1<=len(token)<=4096 or any(ord(x)<32 for x in token):
            raise AccessDenied('GitHub authorization not accepted')
        return token

    def verify_installation(self,installation_id):
        positive_id(installation_id)
        item=self.request('GET',f'/app/installations/{installation_id}',self.jwt())
        if not isinstance(item,dict) or item.get('id')!=installation_id or item.get('app_id')!=int(self.app_id) or item.get('suspended_at'):
            raise AccessDenied('GitHub App installation not accepted')
        return item

    def verify_user_repository(self,user_token,repository,installation_id=None):
        if not isinstance(repository,str) or not re.fullmatch(r'github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
            raise ValidationError('A GitHub repository binding is required')
        if installation_id is not None: positive_id(installation_id)
        installations=([{'id':installation_id}] if installation_id else self.pages('/user/installations',user_token,'installations'))
        for installation in installations:
            identifier=installation.get('id')
            positive_id(identifier)
            try: self.verify_installation(identifier)
            except AccessDenied: continue
            for repo in self.pages(f'/user/installations/{identifier}/repositories',user_token,'repositories'):
                if isinstance(repo,dict) and str(repo.get('full_name','')).casefold()==repository[len('github.com/'):].casefold():
                    positive_id(repo.get('id'))
                    return {'installation_id':identifier,'repository_id':repo['id'],'full_name':repo['full_name']}
        raise AccessDenied('GitHub repository access not accepted')

    def installation_token(self,installation_id,repository_id,write=False):
        if type(write) is not bool: raise ValidationError('Expected a write-scope flag')
        positive_id(installation_id);positive_id(repository_id)
        requested={'contents':'write' if write else 'read','pull_requests':'write' if write else 'read',
                   'checks':'read','statuses':'read'}
        result=self.request('POST',f'/app/installations/{installation_id}/access_tokens',self.jwt(),{
            'repository_ids':[repository_id],'permissions':requested})
        token=result.get('token') if isinstance(result,dict) else None
        if not isinstance(token,str) or not 1<=len(token)<=4096 or any(ord(x)<32 for x in token):
            raise GitHubError('GitHub installation token is invalid')
        repositories=result.get('repositories')
        permissions=result.get('permissions')
        required={'contents','pull_requests','checks','statuses'}
        if (not isinstance(repositories,list) or len(repositories)!=1 or not isinstance(repositories[0],dict)
                or type(repositories[0].get('id')) is not int or repositories[0]['id']!=repository_id
                or not isinstance(permissions,dict) or not required.issubset(permissions)
                or set(permissions)-required-{'metadata'}
                or any(permissions[key]!=requested[key] for key in required)
                or (permissions.get('metadata') is not None and permissions['metadata']!='read')):
            raise GitHubError('GitHub installation token grants exceed requested scope')
        return token

    def _run_bounded(self,func,*args,**kwargs):
        context=_operation.set({'requests':0,'deadline':time.monotonic()+self.OPERATION_SECONDS})
        try: return func(*args,**kwargs)
        finally: _operation.reset(context)

    @staticmethod
    def _repository_path(full_name):
        if not isinstance(full_name,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',full_name):
            raise ValidationError('A GitHub repository full name is required')
        return '/repos/'+quote(full_name,safe='/')

    def find_open_pr(self,installation_id,repository_id,full_name,head):
        """Lookup-before-create: the open same-repo PR for a head branch, or None.

        Uses a read-only token; creation is the only call that mints write scope.
        """
        branch_name(head)
        path=self._repository_path(full_name)
        def lookup():
            token=self.installation_token(installation_id,repository_id)
            owner=full_name.split('/')[0]
            items,_=self.bounded_page(path+'/pulls?'+urlencode({'state':'open','head':owner+':'+head}),token,limit=10)
            for item in items:
                if not isinstance(item,dict) or type(item.get('number')) is not int:
                    raise GitHubError('GitHub PR response is invalid')
                number=positive_id(item['number'])
                head_ref=item.get('head') or {}
                head_repo=head_ref.get('repo') or {}
                if (item.get('state')!='open' or head_ref.get('ref')!=head
                        or head_repo.get('id')!=repository_id):
                    continue
                try: sha=complete_sha(head_ref.get('sha',''))
                except ValidationError: raise GitHubError('GitHub PR response is invalid') from None
                return {'number':number,'state':'open','head_sha':sha,'head_branch':head,
                        'url':f'https://github.com/{full_name}/pull/{number}'}
            return None
        return self._run_bounded(lookup)

    def create_pull_request(self,installation_id,repository_id,full_name,head,base,title,body):
        """Open a PR as a draft (D8); always draft, never ready. Mints write scope."""
        branch_name(head);branch_name(base)
        if head==base: raise ValidationError('PR head and base must differ')
        if (not isinstance(title,str) or not 1<=len(title)<=250 or title!=title.strip()
                or any(ord(char)<32 for char in title)):
            raise ValidationError('PR title is invalid')
        if (not isinstance(body,str) or len(body)>10000
                or any(ord(char)<32 and char not in '\n\t' for char in body)):
            raise ValidationError('PR body is invalid')
        path=self._repository_path(full_name)
        def create():
            token=self.installation_token(installation_id,repository_id,write=True)
            result=self.request('POST',path+'/pulls',token,{
                'title':title,'head':head,'base':base,'body':body,'draft':True})
            if not isinstance(result,dict): raise GitHubError('GitHub PR response is invalid')
            try:
                number=result['number'];positive_id(number)
                if result['state']!='open' or result['base']['repo']['id']!=repository_id:
                    raise GitHubError('GitHub PR identity is invalid')
                sha=complete_sha(result['head']['sha'])
                if result['head']['ref']!=head: raise GitHubError('GitHub PR identity is invalid')
            except (KeyError,TypeError,ValidationError): raise GitHubError('GitHub PR response is invalid') from None
            return {'number':number,'state':'open','head_sha':sha,'head_branch':head,
                    'draft':result.get('draft') is True,
                    'url':f'https://github.com/{full_name}/pull/{number}'}
        return self._run_bounded(create)

    def read_branch_protection(self,installation_id,repository_id,full_name,branch):
        """Branch protection for one branch, or None when unprotected (404).

        Uses a read-only token. Only the sections the merge gate reads are
        normalized: required status checks, required reviews, restrictions.
        """
        branch_name(branch)
        path=self._repository_path(full_name)
        def read():
            token=self.installation_token(installation_id,repository_id)
            try:
                result=self.request('GET',path+'/branches/'+quote(branch,safe='')+'/protection',token)
            except GitHubAccessDenied as error:
                if error.status==404: return None
                raise
            if not isinstance(result,dict): raise GitHubError('GitHub protection response is invalid')
            def section(key):
                value=result.get(key)
                return value if isinstance(value,dict) else None
            checks=section('required_status_checks')
            contexts=[]
            if checks is not None:
                raw=checks.get('contexts')
                if not isinstance(raw,list) or len(raw)>100: raise GitHubError('GitHub protection response is invalid')
                for context in raw:
                    if not isinstance(context,str) or not context or len(context)>200:
                        raise GitHubError('GitHub protection response is invalid')
                    contexts.append(context)
            reviews=section('required_pull_request_reviews')
            count=0
            if reviews is not None:
                count=reviews.get('required_approving_review_count',0)
                if type(count) is not int or count<0: raise GitHubError('GitHub protection response is invalid')
            restrictions=section('restrictions')
            limited={}
            if restrictions is not None:
                for key in ('users','teams','apps'):
                    raw=restrictions.get(key)
                    if raw is None: raw=[]
                    if not isinstance(raw,list) or len(raw)>100: raise GitHubError('GitHub protection response is invalid')
                    names=[]
                    for entry in raw:
                        if not isinstance(entry,dict): raise GitHubError('GitHub protection response is invalid')
                        name=entry.get('login') or entry.get('name') or entry.get('slug')
                        if not isinstance(name,str) or not name: raise GitHubError('GitHub protection response is invalid')
                        names.append(name[:200])
                    limited[key]=names
            return {'required_status_checks':{'contexts':contexts} if checks is not None else None,
                    'required_pull_request_reviews':{'required_approving_review_count':count} if reviews is not None else None,
                    'restrictions':limited if restrictions is not None else None}
        return self._run_bounded(read)

    def read_pull_reviews(self,installation_id,repository_id,full_name,number):
        """PR reviews in API order with a truncation flag; uses a read-only token."""
        positive_id(number)
        path=self._repository_path(full_name)
        def read():
            token=self.installation_token(installation_id,repository_id)
            items,truncated=self.bounded_page(path+'/pulls/'+str(number)+'/reviews',token,limit=100)
            reviews=[]
            for item in items:
                if not isinstance(item,dict): raise GitHubError('GitHub review response is invalid')
                user=item.get('user') or {}
                reviewer=user.get('login') if isinstance(user,dict) else None
                if reviewer is None and isinstance(user,dict): reviewer=user.get('id')
                state=item.get('state')
                if (reviewer is None or state not in ('APPROVED','CHANGES_REQUESTED','COMMENTED','DISMISSED','PENDING')):
                    raise GitHubError('GitHub review response is invalid')
                reviews.append({'reviewer':str(reviewer)[:200],'state':state})
            return {'reviews':reviews,'truncated':truncated}
        return self._run_bounded(read)

    def merge_pull_request(self,installation_id,repository_id,full_name,number,head_sha):
        """Merge a PR with a merge commit, guarded by the expected head SHA (D1).

        Mints write scope. The method is fixed to 'merge' and the expected head
        SHA is passed as 'sha', so a moved head aborts the merge server-side.
        """
        positive_id(number)
        complete_sha(head_sha)
        path=self._repository_path(full_name)
        def merge():
            token=self.installation_token(installation_id,repository_id,write=True)
            try:
                result=self.request('PUT',path+'/pulls/'+str(number)+'/merge',token,
                                    {'sha':head_sha,'merge_method':'merge'})
            except GitHubError as error:
                raise GitHubError('GitHub refused the merge',retryable=error.retryable,
                                  retry_after=error.retry_after,rate_limited=error.rate_limited) from None
            if not isinstance(result,dict) or result.get('merged') is not True:
                raise GitHubError('GitHub merge response is invalid')
            try: sha=complete_sha(result.get('sha',''))
            except ValidationError: raise GitHubError('GitHub merge response is invalid') from None
            return {'merged':True,'sha':sha,'number':number}
        return self._run_bounded(merge)

    def verify_repository(self,installation_id,repository_id,full_name):
        self.verify_installation(installation_id)
        token=self.installation_token(installation_id,repository_id)
        repo=self.request('GET','/repositories/'+str(positive_id(repository_id)),token)
        if not isinstance(repo,dict) or repo.get('id')!=repository_id or repo.get('full_name','').casefold()!=full_name.casefold():
            raise AccessDenied('GitHub repository identity changed')
        return repo

    def repository_state(self,installation_id,repository_id,full_name,branches=(),pr_numbers=(),commit_shas=(),release_ids=()):
        if len(branches)+len(pr_numbers)+len(commit_shas)+len(release_ids)>100:
            raise GitHubError('GitHub synchronization reference limit exceeded')
        context=_operation.set({'requests':0,'deadline':time.monotonic()+self.OPERATION_SECONDS})
        try:
            return self._repository_state(installation_id,repository_id,full_name,branches,pr_numbers,commit_shas,release_ids)
        finally: _operation.reset(context)

    @classmethod
    def _normalize_release(cls,release,release_id,full_name):
        try:
            if not isinstance(release,dict) or type(release.get('id')) is not int or release['id']!=release_id:
                raise GitHubError('GitHub release identity is invalid')
            tag=release.get('tag_name')
            if not isinstance(tag,str) or not tag or len(tag)>250 or any(ord(char)<32 for char in tag):
                raise GitHubError('GitHub release tag is invalid')
            draft,prerelease=release.get('draft'),release.get('prerelease')
            if type(draft) is not bool or type(prerelease) is not bool:
                raise GitHubError('GitHub release state is invalid')
            name=release.get('name')
            if name is None: name=tag
            if not isinstance(name,str) or len(name)>250 or any(ord(char)<32 for char in name):
                raise GitHubError('GitHub release name is invalid')
            target=release.get('target_commitish','')
            if not isinstance(target,str) or len(target)>250 or any(ord(char)<32 for char in target):
                raise GitHubError('GitHub release target is invalid')
            dates={}
            for field in ('created_at','published_at'):
                value=release.get(field)
                if value is not None and (not isinstance(value,str) or len(value)>50 or any(ord(char)<32 for char in value)):
                    raise GitHubError('GitHub release timestamp is invalid')
                dates[field]=value
            assets=release.get('assets',[])
            if not isinstance(assets,list) or len(assets)>1000:
                raise GitHubError('GitHub release assets are invalid')
            safe_assets=[]
            for asset in assets[:cls.RELEASE_ASSET_LIMIT]:
                if not isinstance(asset,dict): raise GitHubError('GitHub release assets are invalid')
                asset_name=asset.get('name')
                size=asset.get('size')
                digest=asset.get('digest')
                if (not isinstance(asset_name,str) or not asset_name or len(asset_name)>250
                        or any(ord(char)<32 for char in asset_name) or type(size) is not int or not 0<=size<2**63
                        or (digest is not None and (not isinstance(digest,str) or len(digest)>100
                            or any(ord(char)<32 for char in digest)))):
                    raise GitHubError('GitHub release asset metadata is invalid')
                safe_assets.append({'name':asset_name,'size':size,'digest':digest})
            from urllib.parse import quote
            state='draft' if draft else 'prerelease' if prerelease else 'published'
            return {'release_id':release_id,'tag_name':tag,'name':name,'state':state,'draft':draft,
                    'prerelease':prerelease,'created_at':dates['created_at'],'published_at':dates['published_at'],
                    'target_commitish':target,'assets':safe_assets,'assets_truncated':len(assets)>cls.RELEASE_ASSET_LIMIT,
                    'url':f'https://github.com/{full_name}/releases/tag/{quote(tag,safe="")}'}
        except (KeyError,TypeError,ValueError):
            raise GitHubError('GitHub release is invalid') from None

    def _repository_state(self,installation_id,repository_id,full_name,branches,pr_numbers,commit_shas,release_ids):
        repo=self.verify_repository(installation_id,repository_id,full_name)
        token=self.installation_token(installation_id,repository_id)
        path='/repos/'+quote(repo['full_name'],safe='/')
        refs={};commits={};unavailable_prs=[];unavailable_commits=[]
        def checks_at(sha):
            complete_sha(sha)
            if sha in commits: return commits[sha]
            checks_truncated=False;statuses_truncated=False
            try:
                checks,checks_truncated=self.bounded_page(path+'/commits/'+quote(sha,safe='')+'/check-runs?filter=latest',token,'check_runs',self.CHECK_LIMIT)
            except GitHubAccessDenied as error:
                if error.status!=404: raise
                checks=[]
            try:
                statuses,statuses_truncated=self.bounded_page(path+'/commits/'+quote(sha,safe='')+'/statuses',token,limit=self.CHECK_LIMIT)
            except GitHubAccessDenied as error:
                if error.status!=404: raise
                statuses=[]
            if any(not isinstance(s,dict) for s in checks+statuses): raise GitHubError('GitHub commit checks are invalid')
            commits[sha]={'checks':[{'head_sha':str(c.get('head_sha',''))[:64],'name':str(c.get('name',''))[:200],
                'status':str(c.get('status',''))[:40],'conclusion':str(c.get('conclusion') or '')[:40]} for c in checks],
                'statuses':[{'head_sha':sha,'context':str(s.get('context',''))[:200],'state':str(s.get('state',''))[:40]} for s in statuses],
                'checks_truncated':checks_truncated,'statuses_truncated':statuses_truncated}
            return commits[sha]
        for branch in branches:
            try:
                ref=self.request('GET',path+'/git/ref/heads/'+quote(branch,safe=''),token)
                refs[branch]=complete_sha(ref['object']['sha'])
            except GitHubAccessDenied as error:
                # A missing branch is represented by absence; repository identity was separately verified.
                if error.status!=404: raise
                continue
            except (KeyError,TypeError): raise GitHubError('GitHub reference is invalid') from None
            checks_at(refs[branch])
        for sha in commit_shas:
            complete_sha(sha)
            try:
                commit=self.request('GET',path+'/commits/'+quote(sha,safe=''),token)
            except GitHubAccessDenied as error:
                if error.status!=404: raise
                unavailable_commits.append(sha)
                continue
            if not isinstance(commit,dict) or commit.get('sha')!=sha:
                raise GitHubError('GitHub commit identity changed')
            checks_at(sha)
        summaries,truncated=self.bounded_page(path+'/pulls?state=open&sort=updated&direction=desc',token,limit=self.DISCOVERY_LIMIT)
        pulls={};details=set(pr_numbers)
        def normalize(pr,number,detail):
            try:
                if (not isinstance(pr,dict) or type(pr.get('number')) is not int or pr['number']!=number
                        or pr['base']['repo']['id']!=repository_id or pr['state'] not in ('open','closed')):
                    raise GitHubError('GitHub PR identity is invalid')
                positive_id(number)
                sha=complete_sha(pr['head']['sha'])
                head_id=(pr['head'].get('repo') or {}).get('id')
                if head_id is not None: positive_id(head_id)
                branch=pr['head']['ref']
                if not isinstance(branch,str) or len(branch)>250: raise GitHubError('GitHub PR branch is invalid')
                base_branch=pr['base'].get('ref')
                if base_branch is not None and (not isinstance(base_branch,str) or not base_branch or len(base_branch)>250):
                    raise GitHubError('GitHub PR branch is invalid')
                mergeable=pr.get('mergeable')
                if mergeable is not None and type(mergeable) is not bool:
                    raise GitHubError('GitHub PR merge state is invalid')
                raw_merge=pr.get('merge_commit_sha')
                merge_commit_sha=complete_sha(raw_merge) if raw_merge is not None else None
                merged=pr['merged'] if detail else False
                if type(merged) is not bool: raise GitHubError('GitHub PR merge state is invalid')
                current=checks_at(sha) if detail else {'checks':[],'statuses':[], 'checks_truncated':False,'statuses_truncated':False}
                return {'number':number,'state':pr['state'],'merged':merged,'head_sha':sha,
                    'head_repository_id':head_id,'head_branch':branch,'base_branch':base_branch,
                    'mergeable':mergeable,'merge_commit_sha':merge_commit_sha,**current,'checks_verified':detail}
            except (KeyError,TypeError,ValidationError): raise GitHubError('GitHub PR response is invalid') from None
        for summary in summaries:
            number=summary.get('number') if isinstance(summary,dict) else None
            pr=normalize(summary,number,False)
            pulls[number]=pr
            if pr['head_repository_id']==repository_id and refs.get(pr['head_branch'])==pr['head_sha']:
                details.add(number)
        for number in sorted(details):
            positive_id(number)
            try: pr=self.request('GET',path+'/pulls/'+str(number),token)
            except GitHubAccessDenied as error:
                if error.status!=404: raise
                unavailable_prs.append(number)
                pulls.pop(number,None)
                continue
            pulls[number]=normalize(pr,number,True)
        releases={};unavailable_release_ids=[]
        summaries,releases_truncated=self.bounded_page(path+'/releases',token,limit=self.RELEASE_DISCOVERY_LIMIT)
        for item in summaries:
            if not isinstance(item,dict) or type(item.get('id')) is not int:
                raise GitHubError('GitHub release identity is invalid')
            release_id=positive_id(item['id'])
            releases[release_id]=self._normalize_release(item,release_id,repo['full_name'])
        for release_id in sorted(set(release_ids)):
            positive_id(release_id)
            if release_id in releases: continue
            try: item=self.request('GET',path+'/releases/'+str(release_id),token)
            except GitHubAccessDenied as error:
                if error.status!=404: raise
                unavailable_release_ids.append(release_id)
                continue
            releases[release_id]=self._normalize_release(item,release_id,repo['full_name'])
        return {'repository_id':repository_id,'full_name':repo['full_name'],'branches':refs,'pull_requests':list(pulls.values()),
                'commits':commits,'unavailable_pr_numbers':unavailable_prs,'unavailable_commit_shas':unavailable_commits,
                'discovery':{'limit':self.DISCOVERY_LIMIT,'truncated':truncated,'state':'open'},
                'releases':sorted(releases.values(),key=lambda release:(release['published_at'] or release['created_at'] or '',release['release_id']),reverse=True),
                'unavailable_release_ids':unavailable_release_ids,
                'release_discovery':{'limit':self.RELEASE_DISCOVERY_LIMIT,'truncated':releases_truncated}}
