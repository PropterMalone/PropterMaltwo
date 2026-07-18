import jwt from 'jsonwebtoken';
import fs from 'fs';
import path from 'path';

const AMO_API_BASE = 'https://addons.mozilla.org/api/v5';
const POLL_INTERVAL_MS = 5_000;
const POLL_TIMEOUT_MS = 10 * 60 * 1_000;

const REQUIRED_ENV_VARS = ['AMO_JWT_ISSUER', 'AMO_JWT_SECRET'];

function printUsage() {
  console.log(`Usage: node scripts/publish-firefox.js [options] [zip-path]

Upload a new version to Firefox Add-ons (AMO).

Options:
  --help    Show this help message

Arguments:
  zip-path  Path to the .zip file (default: most recent packages/*-firefox.zip)

Environment variables (all required):
  AMO_JWT_ISSUER  JWT issuer (API key) from https://addons.mozilla.org/en-US/developers/addon/api/key/
  AMO_JWT_SECRET  JWT secret from the same page`);
}

function createJwt() {
  const issuedAt = Math.floor(Date.now() / 1000);
  const payload = {
    iss: process.env.AMO_JWT_ISSUER,
    jti: crypto.randomUUID(),
    iat: issuedAt,
    exp: issuedAt + 60,
  };
  return jwt.sign(payload, process.env.AMO_JWT_SECRET, { algorithm: 'HS256' });
}

function findLatestFirefoxZip() {
  const packagesDir = path.resolve('packages');
  if (!fs.existsSync(packagesDir)) {
    return null;
  }

  const firefoxZips = fs
    .readdirSync(packagesDir)
    .filter((f) => f.endsWith('-firefox.zip'))
    .map((f) => ({
      name: f,
      path: path.join(packagesDir, f),
      mtime: fs.statSync(path.join(packagesDir, f)).mtimeMs,
    }))
    .sort((a, b) => b.mtime - a.mtime);

  return firefoxZips.length > 0 ? firefoxZips[0].path : null;
}

function validateEnv() {
  const missing = REQUIRED_ENV_VARS.filter((v) => !process.env[v]);
  if (missing.length > 0) {
    console.error(`Missing required environment variables:\n  ${missing.join('\n  ')}`);
    console.error('\nSee PUBLISHING.md for setup instructions.');
    process.exit(1);
  }
}

function getAddonGuid() {
  const manifestPath = path.resolve('manifest.firefox.json');
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
  const guid = manifest?.browser_specific_settings?.gecko?.id;
  if (!guid) {
    console.error('Could not read addon GUID from manifest.firefox.json');
    process.exit(1);
  }
  return guid;
}

function getVersion() {
  const pkg = JSON.parse(fs.readFileSync(path.resolve('package.json'), 'utf-8'));
  return pkg.version;
}

async function amoFetch(endpoint, options = {}) {
  const token = createJwt();
  const url = `${AMO_API_BASE}${endpoint}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      Authorization: `JWT ${token}`,
      ...options.headers,
    },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`AMO API ${response.status} ${response.statusText}: ${body}`);
  }

  return response.json();
}

async function uploadXpi(zipPath) {
  const token = createJwt();
  const fileData = fs.readFileSync(zipPath);
  const blob = new Blob([fileData]);

  const formData = new FormData();
  formData.append('upload', blob, path.basename(zipPath));
  formData.append('channel', 'listed');

  const response = await fetch(`${AMO_API_BASE}/addons/upload/`, {
    method: 'POST',
    headers: { Authorization: `JWT ${token}` },
    body: formData,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Upload failed (${response.status}): ${body}`);
  }

  return response.json();
}

async function pollUpload(uuid) {
  const start = Date.now();

  while (Date.now() - start < POLL_TIMEOUT_MS) {
    const result = await amoFetch(`/addons/upload/${uuid}/`);

    if (result.processed) {
      if (result.valid) {
        return result;
      }
      console.error('Validation failed:', JSON.stringify(result.validation, null, 2));
      process.exit(1);
    }

    process.stdout.write('.');
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }

  throw new Error(`Upload validation timed out after ${POLL_TIMEOUT_MS / 1000}s`);
}

async function createVersion(guid, uploadUuid, version) {
  try {
    return await amoFetch(`/addons/addon/${guid}/versions/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ upload: uploadUuid }),
    });
  } catch (err) {
    // Idempotency: AMO rejects a version that already exists (409 / "already
    // exists"). The desired effect — that version present on AMO — already
    // holds, so a re-dispatch or delete-tag recovery should treat it as
    // success, not a hard failure that leaves a split cross-store state.
    const msg = String(err?.message ?? err);
    if (/already exists/i.test(msg) || /\b409\b/.test(msg)) {
      return { version, alreadyExists: true };
    }
    throw err;
  }
}

async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--help')) {
    printUsage();
    process.exit(0);
  }

  const positionalArgs = args.filter((a) => !a.startsWith('--'));
  const zipPath = positionalArgs[0] || findLatestFirefoxZip();

  if (!zipPath) {
    console.error('No zip file specified and no packages/*-firefox.zip found.');
    console.error('Run `npm run build:firefox` and zip the dist/ directory first.');
    process.exit(1);
  }

  if (!fs.existsSync(zipPath)) {
    console.error(`Zip file not found: ${zipPath}`);
    process.exit(1);
  }

  validateEnv();

  const guid = getAddonGuid();
  const version = getVersion();

  console.log(`Uploading ${path.basename(zipPath)} (v${version}, ${guid})...`);

  const upload = await uploadXpi(zipPath);
  console.log(`Upload UUID: ${upload.uuid}`);

  if (!upload.processed) {
    process.stdout.write('Waiting for validation');
    await pollUpload(upload.uuid);
    console.log(' done');
  } else if (!upload.valid) {
    console.error('Validation failed:', JSON.stringify(upload.validation, null, 2));
    process.exit(1);
  }

  console.log('Creating version...');
  const versionResult = await createVersion(guid, upload.uuid, version);
  if (versionResult.alreadyExists) {
    console.log(`Version ${version} already exists on AMO — idempotent no-op (nothing to submit).`);
  } else {
    console.log(`Version ${versionResult.version} submitted for review.`);
    console.log('AMO will review and publish the listed add-on automatically once approved.');
  }
}

main().catch((err) => {
  console.error('Fatal error:', err.message || err);
  process.exit(1);
});
