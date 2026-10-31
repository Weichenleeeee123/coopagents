"""Bounded GitHub App routes; credentials derive only from bearer headers."""
import json

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, HTMLResponse
from starlette.routing import Route

from .errors import AccessDenied, Conflict, NotFound, ValidationError
from .github_app import GitHubError
from .github_binding_page import binding_page


def single_header(request,name,required=True):
    values=[value for key,value in request.scope.get('headers',[]) if key.lower()==name.encode()]
    if len(values)>1: raise ValidationError('Duplicate request header')
    if not values:
        if required: raise ValidationError('Missing request header')
        return None
    try: value=values[0].decode('ascii')
    except UnicodeError: raise ValidationError('Invalid request header') from None
    if len(value)>4096: raise ValidationError('Request header exceeds limit')
    return value


def bearer(request):
    value=single_header(request,'authorization',False)
    if not value or not value.startswith('Bearer ') or not value[7:] or any(x.isspace() for x in value[7:]):
        raise AccessDenied('Bearer credential required')
    return value[7:]


async def bounded_body(request):
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>65536: raise ValidationError('Request body exceeds limit')
    return bytes(body)


async def body_object(request,schema):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValidationError('Duplicate JSON field')
            result[key]=value
        return result
    try: data=json.loads(await bounded_body(request),object_pairs_hook=pairs)
    except (ValueError,UnicodeError): raise ValidationError('Expected valid JSON') from None
    if not isinstance(data,dict) or set(data)-set(schema): raise ValidationError('Unsupported request fields')
    for key,(kind,required,default) in schema.items():
        if key not in data:
            if required: raise ValidationError('Missing request field')
            data[key]=default
        if data[key] is None and not required and default is None: continue
        if type(data[key]) is not kind: raise ValidationError('Invalid request field type')
    return data


def git_routes(service,sync):
    async def guarded(request,operation):
        try:
            result=await operation(request)
            return result if isinstance(result,HTMLResponse) else JSONResponse(result,headers={'Cache-Control':'no-store'})
        except (ValidationError,AccessDenied,Conflict,NotFound,GitHubError) as error:
            status=400 if isinstance(error,ValidationError) else 401 if isinstance(error,AccessDenied) else 409 if isinstance(error,Conflict) else 404 if isinstance(error,NotFound) else 503 if error.retryable else 502
            return JSONResponse({'error':type(error).__name__,'message':str(error)},status_code=status,headers={'Cache-Control':'no-store'})

    async def authorize(request):
        token=bearer(request)
        data=await body_object(request,{'installation_id':(int,False,None)})
        return await run_in_threadpool(sync.begin_authorization,token,**data)

    async def finish(request):
        token=bearer(request)
        data=await body_object(request,{'state':(str,True,None)})
        return await run_in_threadpool(sync.finish_authorization,token,**data)

    async def callback(request):
        pairs=list(request.query_params.multi_items())
        keys=[key for key,value in pairs]
        if (len(keys)!=len(set(keys)) or not {'state','code'}.issubset(keys)
                or set(keys)-{'state','code','iss'}
                or ('iss' in keys and request.query_params['iss']!='https://github.com/login/oauth')):
            raise ValidationError('Invalid GitHub authorization callback')
        await run_in_threadpool(sync.complete_authorization,request.query_params['state'],request.query_params['code'])
        return HTMLResponse(binding_page('verified'),headers={
            'Cache-Control':'no-store','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"})

    async def link(request):
        token=bearer(request)
        data=await body_object(request,{'task_id':(int,True,None),'branch':(str,False,''),'pr_number':(int,False,None),'commit_sha':(str,False,''),'release_id':(int,False,None),'session_key':(str,False,None),'ownership_epoch':(int,False,None)})
        return await run_in_threadpool(sync.associate,token,**data)

    async def refresh(request):
        token=bearer(request)
        await body_object(request,{})
        return await run_in_threadpool(sync.refresh,token)

    async def webhook(request):
        body=await bounded_body(request)
        delivery=single_header(request,'x-github-delivery')
        event=single_header(request,'x-github-event')
        signature=single_header(request,'x-hub-signature-256')
        return await run_in_threadpool(sync.receive_webhook,delivery,event,signature,body)

    def endpoint(operation):
        async def handler(request): return await guarded(request,operation)
        return handler

    return [Route('/api/git/github/'+name,endpoint(handler),methods=methods) for name,handler,methods in [
        ('authorize',authorize,['POST']),('finish',finish,['POST']),('callback',callback,['GET']),
        ('link',link,['POST']),('refresh',refresh,['POST']),('webhook',webhook,['POST'])]]
