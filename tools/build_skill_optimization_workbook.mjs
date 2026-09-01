#!/usr/bin/env node

import fs from "node:fs/promises";
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
const { SpreadsheetFile, Workbook } = await import(pathToFileURL(artifactModule).href);

const packageDir = path.resolve(
  process.argv[2] ??
    "research/skill-optimization/selection-sample-2026-08-20-to-2026-08-31",
);
const outputPath = path.join(
  packageDir,
  "A股Skill优化样本_2026-08-20至2026-08-31.xlsx",
);
const renderDir = path.resolve(
  process.argv[3] ?? "/private/tmp/a-share-skill-optimization-workbook-render",
);

function parseCsv(text) {
  const input = text.replace(/^\uFEFF/, "");
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < input.length; index += 1) {
    const char = input[index];
    if (quoted) {
      if (char === '"' && input[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field.length || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  const headers = rows.shift() ?? [];
  return rows
    .filter((values) => values.some((value) => value !== ""))
    .map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])));
}

async function readCsv(relativePath) {
  return parseCsv(await fs.readFile(path.join(packageDir, relativePath), "utf8"));
}

async function readJsonl(relativePath) {
  const text = await fs.readFile(path.join(packageDir, relativePath), "utf8");
  return text
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function asNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function asBoolean(value) {
  if (typeof value === "boolean") return value;
  if (value === null || value === undefined || value === "") return null;
  return String(value).toLowerCase() === "true";
}

function asDate(value) {
  if (!value) return null;
  return new Date(`${String(value).slice(0, 10)}T00:00:00+08:00`);
}

function asDateTime(value) {
  if (!value) return null;
  const match = String(value).match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/,
  );
  if (!match) return null;
  const [, year, month, day, hour, minute, second] = match;
  // Preserve the stated Shanghai wall-clock time in Excel instead of shifting it to UTC.
  return new Date(Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
    Number(second),
  ));
}

function text(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function columnLetter(columnNumber) {
  let value = columnNumber;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

const formalSelections = await readCsv("data/formal_selections.csv");
const candidates = await readJsonl("data/candidate_ledger.jsonl");
const decisions = await readJsonl("data/decision_trace.jsonl");
const contracts = await readJsonl("data/review_contracts.jsonl");
const dailyPaths = await readCsv("data/daily_price_volume.csv");
const monitorReviews = await readJsonl("data/monitor_reviews.jsonl");
const marketContext = await readJsonl("data/market_context.jsonl");
const sectorContext = await readJsonl("data/sector_context.jsonl");
const priceContext = await readJsonl("data/price_context.jsonl");
const manifest = JSON.parse(await fs.readFile(path.join(packageDir, "manifest.json"), "utf8"));

const workbook = Workbook.create();
const overview = workbook.worksheets.add("总览");

const palette = {
  navy: "#123B4A",
  teal: "#0F6B67",
  mint: "#DCEFEA",
  pale: "#F4F8F7",
  gold: "#C58B22",
  ink: "#17313A",
  muted: "#60777D",
  line: "#C9D8D6",
  red: "#A33A3A",
  green: "#277A58",
  white: "#FFFFFF",
};

function writeDataSheet(name, columns, rows, options = {}) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const matrix = [
    columns.map((column) => column.header),
    ...rows.map((row) => columns.map((column) => column.value(row))),
  ];
  const lastColumn = columnLetter(columns.length);
  const lastRow = matrix.length;
  const target = sheet.getRange(`A1:${lastColumn}${lastRow}`);
  target.values = matrix;
  target.format.font = { name: "Aptos", size: 9, color: palette.ink };
  target.format.verticalAlignment = "center";
  target.format.borders = { preset: "all", style: "thin", color: palette.line };
  sheet.getRange(`A1:${lastColumn}1`).format = {
    fill: palette.navy,
    font: { name: "Aptos", size: 9, bold: true, color: palette.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    rowHeightPx: 34,
    borders: { preset: "all", style: "thin", color: palette.line },
  };
  if (lastRow > 1) {
    sheet.getRange(`A2:${lastColumn}${lastRow}`).format.fill = palette.white;
    for (let row = 3; row <= lastRow; row += 2) {
      sheet.getRange(`A${row}:${lastColumn}${row}`).format.fill = palette.pale;
    }
  }
  columns.forEach((column, index) => {
    const range = sheet.getRangeByIndexes(0, index, lastRow, 1);
    range.format.columnWidthPx = column.width ?? 110;
    if (column.wrap) range.format.wrapText = true;
    if (column.numberFormat) range.setNumberFormat(column.numberFormat);
  });
  if (options.rowHeight && lastRow > 1) {
    sheet.getRange(`A2:${lastColumn}${lastRow}`).format.rowHeightPx = options.rowHeight;
  } else if (lastRow > 1) {
    sheet.getRange(`A2:${lastColumn}${lastRow}`).format.rowHeightPx = 28;
  }
  sheet.freezePanes.freezeRows(1);
  if (options.freezeColumns) sheet.freezePanes.freezeColumns(options.freezeColumns);
  const table = sheet.tables.add(`A1:${lastColumn}${lastRow}`, true, options.tableName);
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;
  return sheet;
}

const formalSheet = writeDataSheet(
  "正式入选",
  [
    { header: "行动日", value: (r) => asDate(r.action_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "形成日", value: (r) => asDate(r.formation_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "盘前冻结", value: (r) => asDateTime(r.selection_as_of), width: 170, numberFormat: "yyyy-mm-dd hh:mm:ss" },
    { header: "排序", value: (r) => asNumber(r.priority), width: 52, numberFormat: "0" },
    { header: "代码", value: (r) => r.ts_code, width: 88 },
    { header: "名称", value: (r) => r.name, width: 84 },
    { header: "机会类型", value: (r) => r.opportunity_type, width: 150, wrap: true },
    { header: "正式选择依据", value: (r) => r.selection_reason, width: 460, wrap: true },
    { header: "最强反证", value: (r) => r.strongest_counterevidence, width: 390, wrap: true },
    { header: "最近替代比较", value: (r) => r.nearest_comparison, width: 390, wrap: true },
    { header: "截至8/31 D", value: (r) => asNumber(r.outcome_trading_day_count), width: 78, numberFormat: "0" },
    { header: "截至8/31收盘收益", value: (r) => asNumber(r.outcome_close_return), width: 104, numberFormat: "0.00%" },
    { header: "最高收盘收益", value: (r) => asNumber(r.outcome_max_close_return), width: 96, numberFormat: "0.00%" },
    { header: "最高盘中收益", value: (r) => asNumber(r.outcome_max_high_return), width: 96, numberFormat: "0.00%" },
    { header: "MAE", value: (r) => asNumber(r.outcome_mae), width: 82, numberFormat: "0.00%" },
    { header: "行情状态", value: (r) => r.outcome_data_status, width: 125 },
    { header: "旧trace与日志一致", value: (r) => asBoolean(r.trace_log_text_match), width: 104 },
  ],
  formalSelections,
  { tableName: "FormalSelections", freezeColumns: 2, rowHeight: 92 },
);
formalSheet.getRange(`L2:O${formalSelections.length + 1}`).conditionalFormats.add("colorScale", {
  thresholds: ["min", "50%", "max"],
  colors: ["#F4CCCC", "#FFF2CC", "#D9EAD3"],
});

const selectedContracts = contracts.filter((row) => row.final_fate === "selected");
writeDataSheet(
  "复盘合同",
  [
    { header: "行动日", value: (r) => asDate(r.action_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "代码", value: (r) => r.ts_code, width: 88 },
    { header: "名称", value: (r) => r.name, width: 84 },
    { header: "发动机", value: (r) => r.engine_type, width: 180, wrap: true },
    { header: "状态", value: (r) => r.engine_status, width: 82 },
    { header: "市场确认", value: (r) => r.market_recognition_status, width: 88 },
    { header: "市场确认依据", value: (r) => r.market_recognition_basis, width: 300, wrap: true },
    { header: "催化", value: (r) => r.catalyst, width: 320, wrap: true },
    { header: "短期发动机", value: (r) => r.short_term_engine, width: 350, wrap: true },
    { header: "传播链", value: (r) => r.propagation, width: 320, wrap: true },
    { header: "价格确认", value: (r) => r.price_confirmation, width: 330, wrap: true },
    { header: "剩余路径", value: (r) => r.remaining_path, width: 330, wrap: true },
    { header: "基本面锚", value: (r) => r.fundamental_anchor, width: 300, wrap: true },
    { header: "公司风险", value: (r) => r.company_risk, width: 300, wrap: true },
    { header: "关键未知", value: (r) => r.critical_unknown, width: 320, wrap: true },
    { header: "行动条件证据ID", value: (r) => r.action_condition_decision_id, width: 150 },
    { header: "决策证据ID", value: (r) => text(r.decision_ids), width: 220, wrap: true },
    { header: "历史缺口说明", value: (r) => r.normalization_note, width: 260, wrap: true },
  ],
  selectedContracts,
  { tableName: "ReviewContracts", freezeColumns: 3, rowHeight: 92 },
);

writeDataSheet(
  "决策证据",
  [
    { header: "形成日", value: (r) => asDate(r.formation_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "行动日", value: (r) => asDate(r.action_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "代码", value: (r) => r.ts_code, width: 88 },
    { header: "决策ID", value: (r) => r.decision_id, width: 145 },
    { header: "来源Skill", value: (r) => r.source_skill, width: 190, wrap: true },
    { header: "作用", value: (r) => r.decision_role, width: 100 },
    { header: "证据状态", value: (r) => r.evidence_status_at_use, width: 145, wrap: true },
    { header: "决策变化", value: (r) => r.decision_changed, width: 105 },
    { header: "证据ID", value: (r) => r.evidence_id, width: 215, wrap: true },
    { header: "证据版本", value: (r) => r.evidence_version, width: 190, wrap: true },
    { header: "形成日数值", value: (r) => text(r.formation_values), width: 560, wrap: true },
  ],
  decisions,
  { tableName: "DecisionEvidence", freezeColumns: 3, rowHeight: 68 },
);

writeDataSheet(
  "候选账",
  [
    { header: "形成日", value: (r) => asDate(r.formation_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "行动日", value: (r) => asDate(r.action_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "代码", value: (r) => r.ts_code, width: 88 },
    { header: "名称", value: (r) => r.name, width: 84 },
    { header: "最终命运", value: (r) => r.final_fate, width: 88 },
    { header: "机会类型", value: (r) => r.opportunity_type, width: 160, wrap: true },
    { header: "来源Skill", value: (r) => text(r.source_skills), width: 260, wrap: true },
    { header: "进入/淘汰依据", value: (r) => r.primary_reason, width: 480, wrap: true },
    { header: "发动机", value: (r) => r.research_thesis?.engine_type ?? "", width: 190, wrap: true },
    { header: "发动机状态", value: (r) => r.research_thesis?.engine_status ?? "", width: 100 },
    { header: "市场确认", value: (r) => r.research_thesis?.market_recognition?.status ?? "", width: 95 },
    { header: "格式说明", value: (r) => r.normalization_note, width: 260, wrap: true },
  ],
  candidates,
  { tableName: "CandidateLedger", freezeColumns: 4, rowHeight: 64 },
);

const dailySheet = writeDataSheet(
  "逐日路径",
  [
    { header: "事件键", value: (r) => r.event_key, width: 245 },
    { header: "行动日", value: (r) => asDate(r.action_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "代码", value: (r) => r.ts_code, width: 88 },
    { header: "名称", value: (r) => r.name, width: 84 },
    { header: "交易日", value: (r) => asDate(r.trade_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "D", value: (r) => asNumber(r.trading_day_number), width: 45, numberFormat: "0" },
    { header: "状态", value: (r) => r.data_status, width: 135 },
    { header: "开", value: (r) => asNumber(r.open), width: 75, numberFormat: "0.00" },
    { header: "高", value: (r) => asNumber(r.high), width: 75, numberFormat: "0.00" },
    { header: "低", value: (r) => asNumber(r.low), width: 75, numberFormat: "0.00" },
    { header: "收", value: (r) => asNumber(r.close), width: 75, numberFormat: "0.00" },
    { header: "日涨跌", value: (r) => asNumber(r.pct_chg_percent) === null ? null : asNumber(r.pct_chg_percent) / 100, width: 82, numberFormat: "0.00%" },
    { header: "成交量(股)", value: (r) => asNumber(r.volume_shares), width: 110, numberFormat: "#,##0" },
    { header: "成交额(元)", value: (r) => asNumber(r.amount_cny), width: 125, numberFormat: "#,##0" },
    { header: "收盘收益", value: (r) => asNumber(r.close_return_since_entry), width: 88, numberFormat: "0.00%" },
    { header: "最高收盘收益", value: (r) => asNumber(r.max_close_return_so_far), width: 102, numberFormat: "0.00%" },
    { header: "最高盘中收益", value: (r) => asNumber(r.max_high_return_so_far), width: 102, numberFormat: "0.00%" },
    { header: "MAE", value: (r) => asNumber(r.mae_since_entry), width: 78, numberFormat: "0.00%" },
    { header: "峰值回撤", value: (r) => asNumber(r.close_drawdown_from_peak), width: 88, numberFormat: "0.00%" },
  ],
  dailyPaths,
  { tableName: "DailyPaths", freezeColumns: 4, rowHeight: 26 },
);
dailySheet.getRange(`O2:S${dailyPaths.length + 1}`).conditionalFormats.add("colorScale", {
  thresholds: ["min", "50%", "max"],
  colors: ["#F4CCCC", "#FFF2CC", "#D9EAD3"],
});

writeDataSheet(
  "跟踪复盘",
  [
    { header: "报告分析日", value: (r) => asDate(r.report_analysis_date), width: 100, numberFormat: "yyyy-mm-dd" },
    { header: "报告冻结时点", value: (r) => asDateTime(r.report_as_of), width: 170, numberFormat: "yyyy-mm-dd hh:mm:ss" },
    { header: "Episode", value: (r) => r.episode_id, width: 285, wrap: true },
    { header: "当前判断", value: (r) => r.current_assessment, width: 105 },
    { header: "当前复盘", value: (r) => r.current_review, width: 390, wrap: true },
    { header: "弱/断链环节", value: (r) => r.current_weak_or_failed_link, width: 190, wrap: true },
    { header: "最支持解释", value: (r) => r.best_supported_explanation, width: 145 },
    { header: "替代股解释", value: (r) => r.comparison_interpretation, width: 350, wrap: true },
    { header: "原始理由", value: (r) => r.original_reason_plain_language, width: 390, wrap: true },
    { header: "原始风险", value: (r) => r.original_key_risk_plain_language, width: 360, wrap: true },
    { header: "监控状态", value: (r) => r.monitor_state, width: 105 },
    { header: "为什么报告", value: (r) => r.why_reported, width: 360, wrap: true },
  ],
  monitorReviews,
  { tableName: "MonitorReviews", freezeColumns: 3, rowHeight: 82 },
);

writeDataSheet(
  "市场环境",
  [
    { header: "形成日", value: (r) => asDate(r.analysis_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "公式版本", value: (r) => r.formula_version, width: 145 },
    { header: "1日等权", value: (r) => r.equal_weight_return_1d, width: 82, numberFormat: "0.00%" },
    { header: "1日广度", value: (r) => r.breadth_1d, width: 82, numberFormat: "0.00%" },
    { header: "3日等权", value: (r) => r.equal_weight_return_3d, width: 82, numberFormat: "0.00%" },
    { header: "3日广度", value: (r) => r.breadth_3d, width: 82, numberFormat: "0.00%" },
    { header: "5日等权", value: (r) => r.equal_weight_return_5d, width: 82, numberFormat: "0.00%" },
    { header: "5日广度", value: (r) => r.breadth_5d, width: 82, numberFormat: "0.00%" },
    { header: "20日等权", value: (r) => r.equal_weight_return_20d, width: 88, numberFormat: "0.00%" },
    { header: "20日广度", value: (r) => r.breadth_20d, width: 88, numberFormat: "0.00%" },
    { header: "成交额", value: (r) => r.market_turnover_amount, width: 130, numberFormat: "#,##0" },
    { header: "成交/20日", value: (r) => r.turnover_ratio_20d, width: 90, numberFormat: "0.00x" },
    { header: "20日新高占比", value: (r) => r.new_high_20d_share, width: 105, numberFormat: "0.00%" },
    { header: "涨停数", value: (r) => r.limit_up_count, width: 70, numberFormat: "0" },
    { header: "跌停数", value: (r) => r.limit_down_count, width: 70, numberFormat: "0" },
    { header: "覆盖状态", value: (r) => r.coverage_status, width: 100 },
    { header: "限制", value: (r) => r.limitation_notes, width: 300, wrap: true },
  ],
  marketContext,
  { tableName: "MarketContext", freezeColumns: 2, rowHeight: 42 },
);

writeDataSheet(
  "板块上下文",
  [
    { header: "形成日", value: (r) => asDate(r.analysis_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "类型", value: (r) => r.group_type, width: 80 },
    { header: "代码", value: (r) => r.group_code, width: 92 },
    { header: "名称", value: (r) => r.group_name, width: 110 },
    { header: "层级", value: (r) => r.level, width: 58 },
    { header: "成员数", value: (r) => r.member_count, width: 70, numberFormat: "0" },
    { header: "覆盖率", value: (r) => r.member_coverage_ratio, width: 82, numberFormat: "0.00%" },
    { header: "1日相对", value: (r) => r.relative_return_1d, width: 82, numberFormat: "0.00%" },
    { header: "1日广度", value: (r) => r.breadth_1d, width: 82, numberFormat: "0.00%" },
    { header: "3日相对", value: (r) => r.relative_return_3d, width: 82, numberFormat: "0.00%" },
    { header: "3日广度", value: (r) => r.breadth_3d, width: 82, numberFormat: "0.00%" },
    { header: "5日相对", value: (r) => r.relative_return_5d, width: 82, numberFormat: "0.00%" },
    { header: "5日广度", value: (r) => r.breadth_5d, width: 82, numberFormat: "0.00%" },
    { header: "5日换手份额变化", value: (r) => r.turnover_share_change_5d, width: 120, numberFormat: "0.0000%" },
    { header: "前三正贡献", value: (r) => r.top3_positive_contribution_1d, width: 95, numberFormat: "0.00%" },
    { header: "覆盖状态", value: (r) => r.coverage_status, width: 100 },
    { header: "限制", value: (r) => r.limitation_notes, width: 300, wrap: true },
  ],
  sectorContext,
  { tableName: "SectorContext", freezeColumns: 4, rowHeight: 38 },
);

writeDataSheet(
  "形成日价量",
  [
    { header: "形成日", value: (r) => asDate(r.analysis_date), width: 92, numberFormat: "yyyy-mm-dd" },
    { header: "代码", value: (r) => r.ts_code, width: 88 },
    { header: "1日收益", value: (r) => r.return_1d, width: 82, numberFormat: "0.00%" },
    { header: "3日收益", value: (r) => r.return_3d, width: 82, numberFormat: "0.00%" },
    { header: "5日收益", value: (r) => r.return_5d, width: 82, numberFormat: "0.00%" },
    { header: "20日收益", value: (r) => r.return_20d, width: 82, numberFormat: "0.00%" },
    { header: "5日相对市场", value: (r) => r.relative_market_5d, width: 100, numberFormat: "0.00%" },
    { header: "成交额比20日", value: (r) => r.amount_ratio_last_20d, width: 105, numberFormat: "0.00x" },
    { header: "5日价量效率", value: (r) => r.volume_price_efficiency_5d, width: 105, numberFormat: "0.000" },
    { header: "涨停贡献", value: (r) => r.limit_up_return_contribution_5d, width: 88, numberFormat: "0.00%" },
    { header: "60日位置", value: (r) => r.price_location_60d, width: 88, numberFormat: "0.00%" },
    { header: "主行业代码", value: (r) => r.primary_industry_code, width: 100 },
    { header: "主行业", value: (r) => r.primary_industry_name, width: 120 },
    { header: "5日相对行业", value: (r) => r.relative_industry_return_5d, width: 100, numberFormat: "0.00%" },
    { header: "20%目标ATR距离", value: (r) => r.target_atr_distance_20pct, width: 118, numberFormat: "0.00" },
    { header: "覆盖状态", value: (r) => r.coverage_status, width: 100 },
    { header: "情景Case", value: (r) => r.scenario_case_ids, width: 220, wrap: true },
    { header: "情景Control", value: (r) => r.scenario_control_ids, width: 220, wrap: true },
    { header: "限制", value: (r) => r.limitation_notes, width: 260, wrap: true },
  ],
  priceContext,
  { tableName: "FormationPriceContext", freezeColumns: 2, rowHeight: 38 },
);

writeDataSheet(
  "数据清单",
  [
    { header: "相对路径", value: (r) => r.path, width: 480, wrap: true },
    { header: "字节", value: (r) => r.bytes, width: 110, numberFormat: "#,##0" },
    { header: "SHA-256", value: (r) => r.sha256, width: 430 },
  ],
  manifest.files.filter((row) => !row.path.endsWith(".xlsx") && !row.path.endsWith(".inspect.ndjson")),
  { tableName: "DataInventory", freezeColumns: 1, rowHeight: 38 },
);

overview.showGridLines = false;
overview.getRange("A1:H2").merge();
overview.getRange("A1:H2").values = [["A 股五 Skill 优化研究样本"]];
overview.getRange("A1:H2").format = {
  fill: palette.navy,
  font: { name: "Aptos Display", size: 22, bold: true, color: palette.white },
  horizontalAlignment: "left",
  verticalAlignment: "center",
};
overview.getRange("A3:H3").merge();
overview.getRange("A3:H3").values = [[
  "行动日 2026-08-20 至 2026-08-31｜形成日证据按各次 selection_as_of 冻结｜事后行情仅截至 2026-08-31",
]];
overview.getRange("A3:H3").format = {
  fill: palette.mint,
  font: { name: "Aptos", size: 10, bold: true, color: palette.teal },
  verticalAlignment: "center",
  wrapText: true,
};

const metrics = [
  ["正式入选事件", "=COUNTA('正式入选'!F2:F30)"],
  ["不同股票", "=ROWS(UNIQUE('正式入选'!E2:E30))"],
  ["行动日", "=ROWS(UNIQUE('正式入选'!A2:A30))"],
  ["候选账", `=COUNTA('候选账'!C2:C${candidates.length + 1})`],
  ["决策证据", `=COUNTA('决策证据'!A2:A${decisions.length + 1})`],
  ["逐 episode 复盘", `=COUNTA('跟踪复盘'!C2:C${monitorReviews.length + 1})`],
];
metrics.forEach(([label, formula], index) => {
  const row = 5 + Math.floor(index / 3) * 3;
  const column = 1 + (index % 3) * 2;
  const labelRange = overview.getRangeByIndexes(row - 1, column - 1, 1, 2);
  const valueRange = overview.getRangeByIndexes(row, column - 1, 1, 2);
  labelRange.merge();
  valueRange.merge();
  labelRange.values = [[label]];
  valueRange.formulas = [[formula]];
  labelRange.format = {
    fill: palette.teal,
    font: { name: "Aptos", size: 9, bold: true, color: palette.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  valueRange.format = {
    fill: palette.white,
    font: { name: "Aptos Display", size: 20, bold: true, color: palette.navy },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "outside", style: "medium", color: palette.teal },
  };
});

overview.getRange("A12:H12").merge();
overview.getRange("A12:H12").values = [["研究与复盘口径"]];
overview.getRange("A12:H12").format = {
  fill: palette.gold,
  font: { name: "Aptos", size: 11, bold: true, color: palette.white },
  verticalAlignment: "center",
};
overview.getRange("A13:H19").merge();
overview.getRange("A13:H19").values = [[
  "1. 正式选择依据、最强反证和最近替代比较均来自当时冻结记录；8 月 20 日旧 trace 与正式日志的措辞差异双份保留。\n" +
    "2. V4 复盘合同保留发动机、市场确认、催化、传播链、价格确认、剩余路径、基本面锚、风险、关键未知和行动条件证据。\n" +
    "3. 行情 OHLC 为原始价格；跨日收益按 raw_price × adj_factor 相对行动日开盘计算。缺失行情保留 missing_equity_daily，不补猜。\n" +
    "4. 8 月 31 日收盘跟踪报告在 9 月 1 日盘前形成，报告冻结时点原样保留，不能当作 8 月 31 日开盘前证据。\n" +
    "5. 数据包不含完整本地事实仓、公告正文、日志、凭据或个人绝对路径。",
]];
overview.getRange("A13:H19").format = {
  fill: palette.pale,
  font: { name: "Aptos", size: 10, color: palette.ink },
  wrapText: true,
  verticalAlignment: "top",
  borders: { preset: "outside", style: "thin", color: palette.line },
};

overview.getRange("A21:H21").merge();
overview.getRange("A21:H21").values = [["行动日入选数量"]];
overview.getRange("A21:H21").format = {
  fill: palette.navy,
  font: { name: "Aptos", size: 11, bold: true, color: palette.white },
};
const actionDates = [...new Set(formalSelections.map((row) => row.action_date))].sort();
overview.getRange(`A22:B${21 + actionDates.length}`).values = actionDates.map((day) => [asDate(day), null]);
overview.getRange(`A22:A${21 + actionDates.length}`).setNumberFormat("yyyy-mm-dd");
overview.getRange("A22:B22").format.font = { name: "Aptos", size: 10, color: palette.ink };
actionDates.forEach((_, index) => {
  const row = 22 + index;
  overview.getRange(`B${row}`).formulas = [[`=COUNTIF('正式入选'!$A$2:$A$30,A${row})`]];
});
overview.getRange(`A22:B${21 + actionDates.length}`).format = {
  fill: palette.white,
  font: { name: "Aptos", size: 10, color: palette.ink },
  borders: { preset: "all", style: "thin", color: palette.line },
};
overview.getRange(`B22:B${21 + actionDates.length}`).setNumberFormat("0");

for (let column = 0; column < 8; column += 1) {
  overview.getRangeByIndexes(0, column, 32, 1).format.columnWidthPx = 115;
}
overview.getRange("A1:H2").format.rowHeightPx = 34;
overview.getRange("A3:H3").format.rowHeightPx = 34;
overview.getRange("A13:H19").format.rowHeightPx = 26;
overview.freezePanes.freezeRows(3);

const formulaCells = [];
const formulaErrors = [];
for (const sheet of workbook.worksheets.items) {
  const used = sheet.getUsedRange(true);
  if (!used) continue;
  const formulas = used.formulas;
  const values = used.values;
  for (let rowIndex = 0; rowIndex < formulas.length; rowIndex += 1) {
    for (let columnIndex = 0; columnIndex < formulas[rowIndex].length; columnIndex += 1) {
      const formula = formulas[rowIndex][columnIndex];
      if (formula) formulaCells.push({ sheet: sheet.name, rowIndex, columnIndex, formula });
      const value = values[rowIndex][columnIndex];
      if (typeof value === "string" && /^#(REF!|DIV\/0!|VALUE!|NAME\?|N\/A|NUM!|NULL!)/.test(value)) {
        formulaErrors.push({ sheet: sheet.name, rowIndex, columnIndex, value });
      }
    }
  }
}
if (formulaErrors.length) {
  throw new Error(`formula errors detected: ${JSON.stringify(formulaErrors)}`);
}
console.log(JSON.stringify({ formulaCellCount: formulaCells.length, formulaErrors: 0 }));

await fs.mkdir(packageDir, { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);

await fs.mkdir(renderDir, { recursive: true });
for (const sheet of workbook.worksheets.items) {
  const preview = await workbook.render({
    sheetName: sheet.name,
    autoCrop: "all",
    scale: 0.8,
    format: "png",
  });
  const bytes = new Uint8Array(await preview.arrayBuffer());
  await fs.writeFile(path.join(renderDir, `${sheet.name}.png`), bytes);
  const used = sheet.getUsedRange(true);
  console.log(JSON.stringify({
    sheet: sheet.name,
    usedRange: used?.address ?? null,
    rows: used?.rowCount ?? 0,
    columns: used?.columnCount ?? 0,
    render: path.join(renderDir, `${sheet.name}.png`),
  }));
}

// artifact-tool may emit a verbose inspection sidecar during export; it is a
// transient QA file and must not become part of the public research package.
await fs.rm(`${outputPath}.inspect.ndjson`, { force: true });

console.log(JSON.stringify({ outputPath, sheetCount: workbook.worksheets.items.length }));
