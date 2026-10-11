"""Read-only GitHub App REST adapter. No credential-bearing redirects or URLs."""
import json
import math
from contextvars import ContextVar
import os
from pathlib import Path
import re
import time
from urllib.parse import quote, urlencode, urlsplit

from .errors import AccessDenied, ValidationError


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
            value=os.environ.get('CREWMESH_GITHUB_'+name)
            filename=os.environ.get('CREWMESH_GITHUB_'+name+'_FILE') if secret else None
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
                 'User-Agent':'Crewmesh-GitHub-App'}
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
        if (method not in ('GET','POST') or not isinstance(path,str) or not path.startswith('/')
                or path.startswith('//') or '#' in path or any(ord(x)<32 for x in path)
                or '\\' in path or len(path)>2000):
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

    def installation_token(self,installation_id,repository_id):
        positive_id(installation_id);positive_id(repository_id)
        result=self.request('POST',f'/app/installations/{installation_id}/access_tokens',self.jwt(),{
            'repository_ids':[repository_id],'permissions':{'contents':'read','pull_requests':'read','checks':'read','statuses':'read'}})
        token=result.get('token') if isinstance(result,dict) else None
        if not isinstance(token,str) or not 1<=len(token)<=4096 or any(ord(x)<32 for x in token):
            raise GitHubError('GitHub installation token is invalid')
        repositories=result.get('repositories')
        permissions=result.get('permissions')
        required={'contents','pull_requests','checks','statuses'}
        if (not isinstance(repositories,list) or len(repositories)!=1 or not isinstance(repositories[0],dict)
                or type(repositories[0].get('id')) is not int or repositories[0]['id']!=repository_id
                or not isinstance(permissions,dict) or not required.issubset(permissions)
                or set(permissions)-required-{'metadata'} or any(level!='read' for level in permissions.values())):
            raise GitHubError('GitHub installation token grants exceed requested scope')
        return token

    def verify_repository(self,installation_id,repository_id,full_name):
        self.verify_installation(installation_id)
        token=self.installation_token(installation_id,repository_id)
        repo=self.request('GET','/repositories/'+str(positive_id(repository_id)),token)
        if not isinstance(repo,dict) or repo.get('id')!=repository_id or repo.get('full_name','').casefold()!=full_name.casefold():
            raise AccessDenied('GitHub repository identity changed')
        return repo

    def repository_state(self,installation_id,repository_id,full_name,branches=(),pr_numbers=(),commit_shas=()):
        if len(branches)+len(pr_numbers)+len(commit_shas)>100:
            raise GitHubError('GitHub synchronization reference limit exceeded')
        context=_operation.set({'requests':0,'deadline':time.monotonic()+self.OPERATION_SECONDS})
        try:
            return self._repository_state(installation_id,repository_id,full_name,branches,pr_numbers,commit_shas)
        finally: _operation.reset(context)

    def _repository_state(self,installation_id,repository_id,full_name,branches,pr_numbers,commit_shas):
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
                merged=pr['merged'] if detail else False
                if type(merged) is not bool: raise GitHubError('GitHub PR merge state is invalid')
                current=checks_at(sha) if detail else {'checks':[],'statuses':[], 'checks_truncated':False,'statuses_truncated':False}
                return {'number':number,'state':pr['state'],'merged':merged,'head_sha':sha,
                    'head_repository_id':head_id,'head_branch':branch,**current,'checks_verified':detail}
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
        return {'repository_id':repository_id,'full_name':repo['full_name'],'branches':refs,'pull_requests':list(pulls.values()),
                'commits':commits,'unavailable_pr_numbers':unavailable_prs,'unavailable_commit_shas':unavailable_commits,
                'discovery':{'limit':self.DISCOVERY_LIMIT,'truncated':truncated,'state':'open'}}
