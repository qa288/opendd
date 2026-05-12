const DEFAULT_FEISHU_OAUTH_SCOPES = [
  'offline_access',
  'auth:user.id:read',
  'contact:user.base:readonly',
  'contact:user.basic_profile:readonly',
  'contact:contact.base:readonly',
  'wiki:space:retrieve',
  'wiki:node:read',
  'wiki:node:retrieve',
  'space:document:retrieve',
  'docx:document:readonly',
  'sheets:spreadsheet.meta:read',
  'sheets:spreadsheet:read',
  'base:app:read',
  'base:table:read',
  'base:field:read',
  'base:view:read',
  'base:record:retrieve',
  'search:docs:read',
  'im:chat:read',
  'im:chat.members:read',
  'im:message:readonly',
  'im:message.group_msg:get_as_user',
  'im:message.p2p_msg:get_as_user',
  'search:message',
];

function defaultFeishuOAuthScopeText() {
  return DEFAULT_FEISHU_OAUTH_SCOPES.join(' ');
}

function feishuOAuthScopeText(env = process.env) {
  return env.LARK_MCP_SCOPE || defaultFeishuOAuthScopeText();
}

module.exports = {
  DEFAULT_FEISHU_OAUTH_SCOPES,
  defaultFeishuOAuthScopeText,
  feishuOAuthScopeText,
};
