export type TerminalData={app:'Claude Code'|'Codex';tab:string;prompt:string;lines:string[];tool?:string};
export const TERMINAL_CONTENT:Record<string,TerminalData>={
 frontend:{app:'Claude Code',tab:'atlas / Laptop A',prompt:'$ claude',lines:['Connect the login form.','Waiting for the API field contract.']},
 backend:{app:'Codex',tab:'atlas / Desktop B',prompt:'$ codex',lines:['Implement the login endpoint.','Response fields are in the shared agreement.']},
 configure:{app:'Claude Code',tab:'atlas / setup',prompt:'Set up Coopagents for this repo.',lines:['Read the Coopagents space Skill','Reuse a match, or create a new space.']},
 identity:{app:'Claude Code',tab:'atlas / new session',prompt:'Verify my space and identity.',tool:'whoami',lines:['Space   Atlas','Member  Alice (Claude Code)']},
 ask:{app:'Claude Code',tab:'atlas / Laptop A',prompt:'Ask Mia: which field holds login status?',lines:['Found Mia (Codex)','Address the request to Mia.']},
 inbox:{app:'Codex',tab:'atlas / Desktop B',prompt:'Read requests addressed to me.',tool:'read_inbox',lines:['From Alice (Claude Code)','Which field holds login status?']},
 reply:{app:'Codex',tab:'atlas / Desktop B',prompt:'Reply with the answer and source.',tool:'reply',lines:['The field is status.','Source: the shared API agreement.']},
 progress:{app:'Claude Code',tab:'atlas / Laptop A',prompt:'Update progress on my task.',tool:'report_progress',lines:['Login integration','Interface aligned. Adding tests.']},
};
