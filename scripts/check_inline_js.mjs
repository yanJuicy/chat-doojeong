import fs from "node:fs";

const htmlPath = process.argv[2];
if (!htmlPath) {
  throw new Error("usage: node scripts/check_inline_js.mjs <html-file>");
}

const html = fs.readFileSync(htmlPath, "utf8");
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].map(
  (match) => match[1],
);
if (!scripts.length) {
  throw new Error(`no inline scripts found in ${htmlPath}`);
}

scripts.forEach((source, index) => {
  try {
    new Function(source);
  } catch (error) {
    throw new Error(`inline script ${index + 1} has invalid syntax: ${error.message}`);
  }
});

process.stdout.write(`Validated ${scripts.length} inline scripts in ${htmlPath}\n`);
