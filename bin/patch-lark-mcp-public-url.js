#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

const base =
  process.env.LARK_MCP_DIST ||
  '/opt/opendd/lark-openapi/node_modules/@larksuiteoapi/lark-mcp/dist';
const handlerPath = path.join(base, 'auth/handler/handler.js');
const handlerLocalPath = path.join(base, 'auth/handler/handler-local.js');
const marker = 'OPENDD_PUBLIC_URL_ISSUER_PATCH';

function patchFile(file, replacements) {
  let source = fs.readFileSync(file, 'utf8');
  if (source.includes(marker)) {
    console.log(`public-url patch already present in ${file}`);
    return;
  }
  if (
    source.includes('LARK_MCP_PUBLIC_URL') &&
    source.includes('OPENCLAW_PUBLIC_URL') &&
    source.includes('get issuerUrl()')
  ) {
    console.log(`public-url support already present in ${file}`);
    return;
  }
  if (source.includes('new URL(`${this.issuerUrl}/authorize`)')) {
    console.log(`public-url authorize support already present in ${file}`);
    return;
  }
  let changed = false;
  for (const [needle, replacement] of replacements) {
    if (source.includes(needle)) {
      source = source.replace(needle, replacement);
      changed = true;
    }
  }
  if (!changed) {
    throw new Error(`Unable to patch lark-mcp public URL handling: expected block not found in ${file}`);
  }
  fs.writeFileSync(file, source);
  console.log(`patched ${file}`);
}

patchFile(handlerPath, [
  [
    `    get callbackUrl() {
        return \`http://\${this.options.host}:\${this.options.port}/callback\`;
    }
    get issuerUrl() {
        return \`http://\${this.options.host}:\${this.options.port}\`;
    }`,
    `    get callbackUrl() {
        const publicUrl = String(process.env.LARK_MCP_PUBLIC_URL || process.env.OPENCLAW_PUBLIC_URL || '').replace(/\\/$/, '');
        return publicUrl ? \`\${publicUrl}/callback\` : \`http://\${this.options.host}:\${this.options.port}/callback\`;
    }
    get issuerUrl() {
        const publicUrl = String(process.env.LARK_MCP_PUBLIC_URL || process.env.OPENCLAW_PUBLIC_URL || '').replace(/\\/$/, '');
        return publicUrl || \`http://\${this.options.host}:\${this.options.port}\`;
    }
    // ${marker}`,
  ],
  [
    `        const authorizeUrl = new URL(\`http://\${this.options.host}:\${this.options.port}/authorize\`);`,
    `        const publicUrl = String(process.env.LARK_MCP_PUBLIC_URL || process.env.OPENCLAW_PUBLIC_URL || '').replace(/\\/$/, '');
        const authorizeUrl = new URL(publicUrl ? \`\${publicUrl}/authorize\` : \`http://\${this.options.host}:\${this.options.port}/authorize\`); // ${marker}`,
  ],
]);

patchFile(handlerLocalPath, [
  [
    `            const authorizeUrl = new URL(\`http://\${this.options.host}:\${this.options.port}/authorize\`);`,
    `            const publicUrl = String(process.env.LARK_MCP_PUBLIC_URL || process.env.OPENCLAW_PUBLIC_URL || '').replace(/\\/$/, '');
            const authorizeUrl = new URL(publicUrl ? \`\${publicUrl}/authorize\` : \`http://\${this.options.host}:\${this.options.port}/authorize\`); // ${marker}`,
  ],
]);
