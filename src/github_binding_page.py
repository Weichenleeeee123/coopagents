"""Shared static GitHub binding pages; no credentials, scripts, or remote assets."""
import html
import json
import re

# Approved Coopagents v3 SVG, kept inline for CSP and standalone pages.
BRAND_MARK = '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512" role="img" aria-label="Coopagents"><rect width="512" height="512" rx="112" fill="#202124"/><g fill="none" stroke="#fff" stroke-width="56" stroke-linecap="round"><path d="M129.0292 209.5488 A124 124 0 0 1 331.6812 168.3188"/><path d="M331.6812 343.6812 A124 124 0 0 1 129.0292 302.4512"/></g><circle cx="368" cy="256" r="28" fill="#fff"/></svg>'


def binding_page(state, *, app_name='Coopagents', slug=None, settings=None, action=None,
                 preview=False, message=None, repository=None):
    """Static Chinese binding UI; dynamic data is always escaped, never executable."""
    escape = lambda value: html.escape(str(value), quote=True)
    titles = {'ready': '连接 GitHub 仓库', 'registered': 'App 已创建，继续选择仓库',
              'error': '连接暂未完成', 'verified': 'GitHub 访问已验证'}
    descriptions = {
        'ready': '为项目接入只读的 GitHub 交付信息，让队友与 agent 看见同一份进展。',
        'registered': '接下来前往 GitHub，为这个 App 选择需要接入的测试仓库。',
        'error': '这次授权未能完成。请返回接入流程重新发起，再到 GitHub 确认。',
        'verified': '请回到项目工作台，确认并完成本次仓库连接。'}
    if state not in titles:
        raise ValueError('Unknown binding page state')
    if slug is not None and not re.fullmatch(r'[A-Za-z0-9_-]+', slug):
        raise ValueError('Invalid App slug')
    mark = BRAND_MARK
    if state == 'ready' and not preview:
        if not action or not action.startswith('https://github.com/settings/apps/new?state='):
            raise ValueError('Invalid registration form action')
        button = ('<form method="post" action="' + escape(action) + '"><input type="hidden" name="manifest" value="'
                  + escape(json.dumps(settings)) + '"><button class="primary" type="submit">前往 GitHub 确认创建'
                  '<span aria-hidden="true">↗</span></button></form>')
    elif state == 'verified':
        button = '<a class="primary" href="/">返回项目工作台<span aria-hidden="true">→</span></a>'
    elif state == 'registered' and slug:
        button = ('<a class="primary" href="https://github.com/apps/' + escape(slug)
                  + '/installations/new">选择测试仓库并安装<span aria-hidden="true">↗</span></a>')
    else:
        button = ('<button class="primary" disabled>前往 GitHub 确认创建<span aria-hidden="true">↗</span></button>'
                  if state == 'ready' else '<p class="action-note">返回发起连接的页面，重新开始授权。</p>')
    status = {'ready': '等待你确认', 'registered': 'App 已创建', 'error': '需要重新授权', 'verified': '访问已验证 · 待完成连接'}[state]
    detail = '<p class="notice" role="alert">' + escape(message) + '</p>' if message else ''
    preview_note = '<div class="preview">页面预览 · 未执行 GitHub 操作</div>' if preview else ''
    hint = ('在 GitHub 安装页选择「Only select repositories」，仅勾选这里列出的测试仓库。'
            if state == 'registered' else '访问已验证并不代表连接已完成；请在原项目中继续确认。' if state == 'verified'
            else '你可以在 GitHub 确认前查看 App 名称与所有权限。')
    repository_row = ('<div class="row"><div class="label">目标仓库</div><div class="value repo">'
                      + escape(repository) + '</div></div>') if repository else ''
    steps = ('GitHub 授权', '验证访问', '完成连接') if state == 'verified' else ('创建 App', '选择仓库', '完成连接')
    current = 2 if state == 'verified' else 1 if state == 'registered' else 0
    progress = '<i aria-hidden="true"></i>'.join(
        ('<strong aria-current="step">' if index == current else '<span>')
        + f'{index + 1:02d} ' + label + ('</strong>' if index == current else '</span>')
        for index, label in enumerate(steps))
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>连接 GitHub · Coopagents</title>
<style>
:root{color-scheme:light;--ink:#202124;--muted:#62666d;--line:#e3e5e8;--wash:#f7f8fa}
*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:14px/1.65 "Segoe UI","Microsoft YaHei",sans-serif}
main{width:min(100% - 48px,640px);margin:64px auto 40px}.brand{display:flex;align-items:center;gap:10px;font-size:18px;font-weight:600}
.brand svg{width:32px;height:32px;flex:none}.brand span{font-size:12px;font-weight:400;color:var(--muted);margin-left:auto}
.surface{background:#fff;border:1px solid var(--line);border-radius:12px;margin-top:28px;padding:36px 40px 32px}
.step{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--muted);margin-bottom:22px}.step i{height:1px;width:22px;background:var(--line)}
.step strong{font-weight:500;color:var(--ink)}h1{font-size:26px;line-height:1.4;font-weight:600;margin:0 0 12px;letter-spacing:-.4px}
p{margin:0}a,button{-webkit-tap-highlight-color:transparent}p.description{color:var(--muted);max-width:440px}
.status{display:inline-flex;align-items:center;gap:6px;font-size:12px;margin:24px 0 18px}.status:before{content:"";height:6px;width:6px;border-radius:50%;background:#62666d}
.registered .status:before{background:#287351}.error .status:before{background:#ad4737}.details{border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:18px 0;margin-bottom:22px}
.row{display:grid;grid-template-columns:72px minmax(0,1fr);gap:16px}.row+.row{margin-top:14px}.label{font-size:12px;color:var(--muted);padding-top:1px}
.value{font-size:13px;overflow-wrap:anywhere;min-width:0}.repo{font:12px/1.7 Consolas,"SFMono-Regular",monospace}.scope{margin-top:4px;color:var(--muted);font-size:12px}
.permissions{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.permissions span{border:1px solid var(--line);border-radius:4px;padding:2px 7px;font-size:11px;color:var(--muted)}
.hint{color:var(--muted);font-size:12px;margin-bottom:24px}.primary{display:flex;justify-content:center;align-items:center;gap:12px;width:100%;border:1px solid var(--ink);border-radius:7px;min-height:44px;padding:10px 16px;background:var(--ink);color:#fff;text-decoration:none;font:500 14px/1.5 "Segoe UI","Microsoft YaHei",sans-serif;cursor:pointer}
.primary:hover{background:#36383c}.primary:disabled{opacity:.5;cursor:default}:focus-visible{outline:2px solid #386aa0;outline-offset:4px}
.footnote{margin-top:13px;text-align:center;color:var(--muted);font-size:12px}.footer{text-align:center;color:var(--muted);font-size:12px;margin-top:22px}
.notice{padding:12px 14px;background:var(--wash);border-radius:6px;font-size:13px;margin-top:18px}.preview{padding:8px 12px;text-align:center;border:1px dashed var(--line);border-radius:6px;color:var(--muted);font-size:12px;margin-top:20px}.action-note{color:var(--muted);font-size:13px}
@media(max-width:480px){main{width:calc(100% - 32px);margin:28px auto}.brand span{font-size:11px}.surface{margin-top:24px;padding:28px 22px 24px;border-radius:10px}h1{font-size:23px}.row{grid-template-columns:56px minmax(0,1fr);gap:12px}.step{gap:7px;font-size:11px}.step i{width:14px}}
</style></head><body><main><header class="brand">''' + mark + '''<b>Coopagents</b><span>GitHub 接入</span></header>''' + preview_note + '''
<section class="surface ''' + escape(state) + '''" aria-labelledby="page-title"><nav class="step" aria-label="接入进度">
''' + progress + '''</nav>
<h1 id="page-title">''' + titles[state] + '''</h1><p class="description">''' + descriptions[state] + '''</p>''' + detail + '''
<div class="status">''' + status + '''</div><div class="details"><div class="row"><div class="label">GitHub App</div><div class="value">''' + escape(app_name) + '''</div></div>
''' + repository_row + '''
<div class="row"><div class="label">访问范围</div><div class="value">仅你选择的仓库 · 只读权限<p class="scope">读取代码、PR 与检查状态，不修改仓库内容。</p>
<div class="permissions"><span>代码</span><span>Pull requests</span><span>Checks / Statuses</span></div></div></div></div>
<p class="hint">''' + hint + '''</p>''' + button + '''<p class="footnote">''' + ('安装后还需回到项目完成连接。' if state == 'registered' else '回到原项目后，连接状态以工作台显示为准。' if state == 'verified'
        else '授权范围由你在 GitHub 上确认。') + '''</p></section>
<footer class="footer">与你的队友，保持同一份交付上下文。</footer></main></body></html>'''
