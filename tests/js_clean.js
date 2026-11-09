// Cleans every file in argv[2] with the browser code and writes NAME to argv[3], plus report.json
const fs = require("fs"), path = require("path");
const S = require("../docs/scrub.js");
const [, , inDir, outDir] = process.argv;
const reports = {};
for (const name of fs.readdirSync(inDir).sort()) {
  const data = new Uint8Array(fs.readFileSync(path.join(inDir, name)));
  try {
    const r = S.clean(data);
    fs.writeFileSync(path.join(outDir, name), r.data);
    reports[name] = { gps: r.report.gps, fields: r.report.fields, removed: r.report.removed, trailer: r.report.trailer, orientation: r.report.orientation };
  } catch (e) {
    reports[name] = { error: e.message };
  }
}
fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(reports));
