#!/usr/bin/env node

import path from "node:path";
import { pathToFileURL } from "node:url";

const nodeModules = process.env.CODEX_NODE_MODULES;
if (!nodeModules) {
  throw new Error("CODEX_NODE_MODULES must point to the bundled dependency directory");
}
const artifactModule = path.join(
  nodeModules,
  "@oai",
  "artifact-tool",
  "dist",
  "artifact_tool.mjs",
);
const { FileBlob, SpreadsheetFile } = await import(pathToFileURL(artifactModule).href);

const workbookPath = path.resolve(process.argv[2]);
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const errors = [];
const sheets = [];
let formulaCount = 0;
for (const sheet of workbook.worksheets.items) {
  const used = sheet.getUsedRange(true);
  const values = used?.values ?? [];
  const formulas = used?.formulas ?? [];
  for (let row = 0; row < values.length; row += 1) {
    for (let column = 0; column < values[row].length; column += 1) {
      const value = values[row][column];
      if (formulas[row]?.[column]) formulaCount += 1;
      if (
        typeof value === "string" &&
        /^#(REF!|DIV\/0!|VALUE!|NAME\?|N\/A|NUM!|NULL!)/.test(value)
      ) {
        errors.push({ sheet: sheet.name, row, column, value });
      }
    }
  }
  sheets.push({
    name: sheet.name,
    usedRange: used?.address ?? null,
    rows: used?.rowCount ?? 0,
    columns: used?.columnCount ?? 0,
  });
}
if (errors.length) {
  throw new Error(`formula errors detected: ${JSON.stringify(errors)}`);
}
console.log(JSON.stringify({
  status: "PASS",
  workbookPath,
  sheetCount: sheets.length,
  formulaCount,
  formulaErrors: 0,
  sheets,
}));
