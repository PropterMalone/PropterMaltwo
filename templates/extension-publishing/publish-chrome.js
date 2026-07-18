import chromeWebstoreUpload from 'chrome-webstore-upload';
import fs from 'fs';
import path from 'path';

const REQUIRED_ENV_VARS = [
  'CWS_CLIENT_ID',
  'CWS_CLIENT_SECRET',
  'CWS_REFRESH_TOKEN',
  'CWS_EXTENSION_ID',
];

function printUsage() {
  console.log(`Usage: node scripts/publish-chrome.js [options] [zip-path]

Upload and publish the extension to Chrome Web Store.

Options:
  --upload-only   Upload without publishing (for review-first workflow)
  --help          Show this help message

Arguments:
  zip-path        Path to the .zip file (default: most recent packages/*-chrome.zip)

Environment variables (all required):
  CWS_CLIENT_ID      Google OAuth client ID
  CWS_CLIENT_SECRET  Google OAuth client secret
  CWS_REFRESH_TOKEN  Google OAuth refresh token
  CWS_EXTENSION_ID   Chrome Web Store extension ID`);
}

function findLatestChromeZip() {
  const packagesDir = path.resolve('packages');
  if (!fs.existsSync(packagesDir)) {
    return null;
  }

  const chromeZips = fs
    .readdirSync(packagesDir)
    .filter((f) => f.endsWith('-chrome.zip'))
    .map((f) => ({
      name: f,
      path: path.join(packagesDir, f),
      mtime: fs.statSync(path.join(packagesDir, f)).mtimeMs,
    }))
    .sort((a, b) => b.mtime - a.mtime);

  return chromeZips.length > 0 ? chromeZips[0].path : null;
}

function validateEnv() {
  const missing = REQUIRED_ENV_VARS.filter((v) => !process.env[v]);
  if (missing.length > 0) {
    console.error(`Missing required environment variables:\n  ${missing.join('\n  ')}`);
    console.error('\nSee PUBLISHING.md for setup instructions.');
    process.exit(1);
  }
}

async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--help')) {
    printUsage();
    process.exit(0);
  }

  const uploadOnly = args.includes('--upload-only');
  const positionalArgs = args.filter((a) => !a.startsWith('--'));
  const zipPath = positionalArgs[0] || findLatestChromeZip();

  if (!zipPath) {
    console.error('No zip file specified and no packages/*-chrome.zip found.');
    console.error('Run `npm run build` and zip the dist/ directory first.');
    process.exit(1);
  }

  if (!fs.existsSync(zipPath)) {
    console.error(`Zip file not found: ${zipPath}`);
    process.exit(1);
  }

  validateEnv();

  const store = chromeWebstoreUpload({
    extensionId: process.env.CWS_EXTENSION_ID,
    clientId: process.env.CWS_CLIENT_ID,
    clientSecret: process.env.CWS_CLIENT_SECRET,
    refreshToken: process.env.CWS_REFRESH_TOKEN,
  });

  const zipStream = fs.createReadStream(zipPath);
  console.log(`Uploading ${path.basename(zipPath)}...`);

  const uploadResult = await store.uploadExisting(zipStream);

  // Whitelist SUCCESS: IN_PROGRESS/FAILURE/NOT_FOUND must not fall through to
  // publish() (IN_PROGRESS means CWS is still processing a large zip).
  if (uploadResult.uploadState !== 'SUCCESS') {
    console.error(
      `Upload not successful (state: ${uploadResult.uploadState}):`,
      JSON.stringify(uploadResult, null, 2)
    );
    process.exit(1);
  }

  console.log(`Upload successful (state: ${uploadResult.uploadState})`);

  if (uploadOnly) {
    console.log(
      'Skipping publish (--upload-only). Submit for review manually or re-run without --upload-only.'
    );
    return;
  }

  console.log('Publishing...');
  const publishResult = await store.publish();

  if (publishResult.status.includes('OK')) {
    console.log('Published successfully.');
  } else {
    console.error('Publish response:', JSON.stringify(publishResult, null, 2));
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Fatal error:', err.message || err);
  process.exit(1);
});
