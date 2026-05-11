#!/usr/bin/env node
const fs = require('fs');

const target =
  process.env.LARK_MCP_STORAGE_MANAGER ||
  '/opt/opendd/lark-openapi/node_modules/@larksuiteoapi/lark-mcp/dist/auth/utils/storage-manager.js';

const marker = 'OPENDD file-backed encryption key fallback enabled.';
let source = fs.readFileSync(target, 'utf8');

if (source.includes(marker)) {
  process.exit(0);
}

const needle = `        catch (error) {
            logger_1.logger.warn(\`[StorageManager] Failed to initialize encryption: \${error}\`);
            throw error;
        }`;

const replacement = `        catch (error) {
            logger_1.logger.warn(\`[StorageManager] Failed to initialize encryption: \${error}\`);
            try {
                this.ensureStorageDir();
                const fallbackKeyFile = path_1.default.join(config_1.AUTH_CONFIG.STORAGE_DIR, 'encryption-key');
                let key = process.env.LARK_MCP_STORAGE_KEY || '';
                if (!key && fs_1.default.existsSync(fallbackKeyFile)) {
                    key = fs_1.default.readFileSync(fallbackKeyFile, 'utf8').trim();
                }
                if (!key) {
                    key = encryption_1.EncryptionUtil.generateKey();
                    fs_1.default.writeFileSync(fallbackKeyFile, key, { mode: 0o600 });
                }
                this.encryptionUtil = new encryption_1.EncryptionUtil(key);
                logger_1.logger.warn('[StorageManager] ${marker}');
            }
            catch (fallbackError) {
                logger_1.logger.warn(\`[StorageManager] Failed to initialize fallback encryption: \${fallbackError}\`);
                throw error;
            }
        }`;

if (!source.includes(needle)) {
  throw new Error(`Unable to patch lark-mcp storage manager: expected block not found in ${target}`);
}

source = source.replace(needle, replacement);
fs.writeFileSync(target, source);
console.log(`patched ${target}`);
