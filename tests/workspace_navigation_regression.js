'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const html=fs.readFileSync('src/static/index.html','utf8');
const app=fs.readFileSync('src/static/app.js','utf8');
for(const [view,label] of [['overview','概览'],['tasks','任务'],['requests','协作'],['contracts','共享上下文'],['delivery','交付'],['members','成员与 agent'],['repository','项目设置']]){
  assert.match(html,new RegExp('data-view="'+view+'"[^>]*>[\\s\\S]*?'+label));
  assert.ok(html.includes('id="view-'+view+'"'),'Missing page container '+view);
}
assert.ok(html.includes('id="view-tasks"'),'Task board page exists');
assert.match(html,/id="tasks"\s+class="kanban-board"/,'Initial task page defaults to the board');
const overview=html.slice(html.indexOf('id="view-overview"'),html.indexOf('id="view-tasks"'));
for(const id of ['capability-discovery','delivery-graph','project-assets','project-activity','shared-context'])assert.ok(!overview.includes('id="'+id+'"'),'Overview must not embed full '+id);
assert.match(html,/data-context-tab="agreements"/);assert.match(html,/data-context-tab="files"/);assert.match(html,/data-context-tab="records"/);
assert.match(html,/id="workspace-project-dialog"/);assert.match(html,/id="workspace-project-list"/);
assert.match(html,/id="view-members"[^>]*>[\s\S]*id="capability-discovery"/);
assert.match(html,/id="view-delivery"[^>]*>[\s\S]*id="delivery-graph"/);
assert.doesNotMatch(html,/data-view="members"[^>]*Harness 支持矩阵/);
assert.match(app,/function renderCapabilities\(\).*showMatrix:false/);
assert.match(app,/function renderDeliveryTraceability\(\).*CoopagentsDeliveryGraph/);
assert.match(app,/setView\(routeView\(\)\|\|'tasks',\{push:false\}\);/,'Project entry defaults to the task board and restores routed views');
assert.match(html,/id="workspace-switcher-current"/);
console.log('Workspace navigation, view ownership, overview density, project switcher and default board passed');

assert.doesNotMatch(app,/\['members','tasks','requests','contracts'/,'Logout cleanup must not require removed members container');
console.log('Logout cleanup stays aligned with the served markup passed');
console.log('Logout cleanup stays aligned with the served markup passed');
