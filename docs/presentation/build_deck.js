// Builds docs/presentation/Intelligent-Procurement-Agent.pptx
// Run from anywhere:  node docs/presentation/build_deck.js
// Uses the Kiro pptx skill (.kiro/skills/pptx): pptxgenjs + apply_theme.js.
// Figures come from the repository and from live runs on 21 November 2026 (tests, timings,
// Bedrock call counts, catalogue results). The savings on the Result slide are a labelled estimate.
// Supplier names are real; all prices, stock and lead times are mocked.
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const ROOT = path.resolve(__dirname, "..", "..");
const { applyTheme } = require(path.join(ROOT, ".kiro/skills/pptx/scripts/apply_theme.js"));
const ASSETS = path.join(__dirname, "assets");
const OUT = path.join(__dirname, "Intelligent-Procurement-Agent.pptx");
const asset = (f) => path.join(ASSETS, f);

// Palette matches the app's UI: midnight navy dominates, indigo for the agent,
// orange for the human approval step, green for purchase orders.
const THEME = {
  name: "Procurement Agent",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "0F172A", lt1: "FFFFFF", dk2: "1E2761", lt2: "EEF2FF",
    accent1: "4F46E5", accent2: "0EA5E9", accent3: "16A34A", accent4: "EA580C",
    accent5: "DC2626", accent6: "64748B", hlink: "4F46E5", folHlink: "6D28D9",
  },
};
const HEX = THEME.colors; // for hex-only options (shadows, grid lines, per-bar chart colors)

const W = 13.333, M = 0.6;          // LAYOUT_WIDE width, slide margin
const CW = W - 2 * M;               // content width
const TOP = 1.55;                   // content starts below the title

async function iconPng(Icon, color = "#FFFFFF") {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Icon, { color, size: 256 }));
  const buf = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  pres.title = "Intelligent Procurement Agent";
  pres.author = "RoyalCyber hackathon team";
  pres.subject = "Hackathon demo, November 2026";
  const C = pres.SchemeColor;

  const ICON = {};
  for (const n of ["FaShoppingCart", "FaRobot", "FaBalanceScale", "FaUserCheck", "FaFileInvoice", "FaUser",
    "FaUserTie", "FaEnvelopeOpenText", "FaTable", "FaInbox", "FaQuestionCircle", "FaShieldAlt", "FaLock",
    "FaCogs", "FaDollarSign", "FaClock", "FaCloud", "FaBan", "FaClipboardList", "FaIndustry",
    "FaLayerGroup", "FaExchangeAlt", "FaPlug", "FaSearch"]) {
    ICON[n] = await iconPng(fa[n]);
  }

  // ------------------------------------------------------------- layouts
  pres.defineSlideMaster({
    title: "TITLE_DARK",
    background: { color: C.text2 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 1.3, w: 11.7, h: 1.5,
        fontSize: 48, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "subtitle", type: "body", x: 0.8, y: 2.95, w: 11.4, h: 1.0,
        fontSize: 20, color: C.background2, valign: "top", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "meta", type: "body", x: 0.8, y: 6.55, w: 11.7, h: 0.45,
        fontSize: 12, color: C.background2, valign: "middle", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "CLOSING_DARK",
    background: { color: C.text2 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: M, y: 0.45, w: CW, h: 0.95,
        fontSize: 40, bold: true, color: C.background1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "CONTENT",
    background: { color: C.background1 },
    margin: [0.5, 0.6, 0.6, 0.6],
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: M, y: 0.4, w: CW, h: 0.95,
        fontSize: 36, bold: true, color: C.text2, valign: "middle", align: "left", margin: 0 }, text: "" } },
      { text: { text: "Intelligent Procurement Agent · RoyalCyber · simulated supplier catalogues, mocked prices",
        options: { x: M, y: 7.0, w: 9.5, h: 0.3, fontSize: 10, color: C.accent6, margin: 0 } } },
    ],
    slideNumber: { x: 12.15, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: C.accent6, align: "right" },
  });

  // ------------------------------------------------------------- helpers
  const shadow = () => ({ type: "outer", color: HEX.dk1, opacity: 0.12, blur: 8, offset: 2, angle: 90 });
  const card = (s, x, y, w, h, name, fill = C.background2) =>
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.12, fill: { color: fill },
      line: { color: fill, width: 0 }, shadow: shadow(), objectName: name });
  const icon = (s, key, x, y, d, color, name) => {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color }, line: { color, width: 0 },
      objectName: name + " circle" });
    s.addImage({ data: ICON[key], x: x + d * 0.24, y: y + d * 0.24, w: d * 0.52, h: d * 0.52,
      objectName: name + " icon", altText: name });
  };
  const text = (s, t, o) => s.addText(t, Object.assign({ isTextBox: true, margin: 0, valign: "top",
    fontSize: 16, color: C.text1 }, o));
  const bullets = (items) => items.map((t, i) => ({ text: t, options: { bullet: true,
    breakLine: i < items.length - 1, paraSpaceAfter: 6 } }));
  const arrow = (s, x1, y1, x2, y2, name) => s.addShape(pres.shapes.LINE, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
    flipV: y2 < y1, line: { color: HEX.accent6, width: 1.75, endArrowType: "triangle" }, objectName: name });
  const numberDot = (s, n, x, y, d, color, name) => {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color }, line: { color, width: 0 }, objectName: name });
    text(s, String(n), { x, y, w: d, h: d, fontSize: 16, bold: true, color: C.background1, align: "center",
      valign: "middle" });
  };
  const picture = (s, file, x, y, w, pxW, pxH, name, alt) => {
    const h = w * pxH / pxW;
    s.addImage({ path: asset(file), x, y, w, h, objectName: name, altText: alt });
    return h;
  };

  // ============================================================= 1 Title
  pres.addSection({ title: "Introduction" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction" });
  s.addText("Intelligent Procurement Agent", { placeholder: "title" });
  s.addText("From a plain-English request for manufacturing parts to approved purchase orders, one per supplier, " +
    "with a person in control", { placeholder: "subtitle" });
  s.addText("RoyalCyber · Hackathon demo · November 2026 · Amazon Bedrock (us-east-1)", { placeholder: "meta" });
  const flow = [["FaShoppingCart", "Ask", C.accent2], ["FaRobot", "Extract", C.accent1],
    ["FaSearch", "Search", C.accent1], ["FaUserCheck", "Approve", C.accent4], ["FaFileInvoice", "Order", C.accent3]];
  flow.forEach(([k, label, col], i) => {
    const x = 0.8 + i * 1.75;
    icon(s, k, x, 4.55, 0.9, col, label);
    text(s, label, { x: x - 0.25, y: 5.55, w: 1.4, h: 0.4, fontSize: 16, bold: true, color: C.background1,
      align: "center" });
  });
  s.addNotes("Introduce the team and the one-line pitch: an engineer describes the parts a build needs in plain " +
    "English; the agent searches supplier catalogues, checks every spec, and prepares one approval request and one " +
    "purchase order per supplier. Nothing is ordered until an approver signs off. The five icons are the flow we will demo.");

  // ============================================================= 2 Problem
  pres.addSection({ title: "Problem" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Problem" });
  s.addText("Sourcing parts for one build is slow and manual", { placeholder: "title" });
  const personas = [
    ["FaUser", C.accent1, "Requester · engineer",
      "Needs 100 pressure sensors, 6 flow meters and 200 proximity sensors for a test stand by 30 January. " +
      "Checks each supplier's datasheets and prices by hand."],
    ["FaUserTie", C.accent4, "Approver · procurement",
      "Gets one email per part with no comparison and no spec check, and approves from memory. Nothing records why."],
  ];
  personas.forEach(([k, col, who, body], i) => {
    const y = TOP + 0.1 + i * 2.6;
    card(s, M, y, 5.6, 2.3, who + " card");
    icon(s, k, M + 0.3, y + 0.3, 0.75, col, who);
    text(s, who, { x: M + 1.25, y: y + 0.38, w: 4.1, h: 0.5, fontSize: 22, bold: true, color: C.text2 });
    text(s, body, { x: M + 0.3, y: y + 1.15, w: 5.0, h: 1.05, fontSize: 16 });
  });
  text(s, "What goes wrong today", { x: 6.9, y: TOP + 0.15, w: 5.8, h: 0.5, fontSize: 22, bold: true,
    color: C.text2 });
  [["FaTable", "Every part is sourced separately, supplier site by supplier site"],
    ["FaClipboardList", "Specs such as range, output and connection are checked by eye"],
    ["FaInbox", "Approvals sit in inboxes while delivery deadlines slip"],
    ["FaQuestionCircle", "No record of why a supplier or model won"]].forEach(([k, t], i) => {
    const y = TOP + 0.95 + i * 1.12;
    icon(s, k, 6.9, y, 0.62, C.accent6, "Problem " + (i + 1));
    text(s, t, { x: 7.8, y: y + 0.02, w: 4.9, h: 0.62, fontSize: 18, valign: "middle" });
  });
  s.addNotes("Who has the problem: engineers who need several parts by a date, and procurement who approve the " +
    "spend. Today each part is sourced and approved separately, specs are checked by eye, and there is no trail. " +
    "Keep this under a minute.");

  // ============================================================= 3 How it works
  pres.addSection({ title: "Solution" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Solution" });
  s.addText("Five steps from request to purchase orders", { placeholder: "title" });
  const steps = [
    ["FaShoppingCart", C.accent2, "1  Ask", "Describe one part or a whole bill of materials in plain English."],
    ["FaRobot", C.accent1, "2  Extract", "Bedrock reads each product, quantity, spec and budget. Gaps are asked for, never guessed."],
    ["FaSearch", C.accent1, "3  Search", "5 supplier catalogues searched per product; every spec checked; deadline first, then price."],
    ["FaUserCheck", C.accent4, "4  Approve", "One approval request per supplier. Each is approved or rejected on its own."],
    ["FaFileInvoice", C.accent3, "5  Order", "Each approval issues one PDF purchase order with all that supplier's parts."],
  ];
  const sw = 2.25, sg = (CW - 5 * sw) / 4;
  steps.forEach(([k, col, title, body], i) => {
    const x = M + i * (sw + sg);
    card(s, x, TOP + 0.1, sw, 3.55, "Step " + (i + 1) + " card");
    icon(s, k, x + 0.25, TOP + 0.35, 0.75, col, "Step " + (i + 1));
    text(s, title, { x: x + 0.25, y: TOP + 1.3, w: sw - 0.4, h: 0.45, fontSize: 20, bold: true, color: C.text2 });
    text(s, body, { x: x + 0.25, y: TOP + 1.85, w: sw - 0.4, h: 1.7, fontSize: 15 });
  });
  icon(s, "FaRobot", M, 5.55, 0.6, C.accent2, "Bedrock role");
  text(s, "Amazon Bedrock (Nova Lite) reads the request, plans the tool calls and writes the summary.",
    { x: M + 0.8, y: 5.55, w: 5.1, h: 0.85, fontSize: 16, valign: "middle" });
  icon(s, "FaLock", 6.75, 5.55, 0.6, C.text2, "App role");
  text(s, "Python checks specs, ranks, groups by supplier and issues POs. The AI has no tool that can order.",
    { x: 7.55, y: 5.55, w: 5.18, h: 0.85, fontSize: 16, valign: "middle" });
  s.addNotes("Walk the five steps. The split at the bottom matters: the model handles language and planning; " +
    "tested code makes every decision that matters; step 4 is always a person.");

  // ============================================================= 4 One PO per supplier
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Solution" });
  s.addText("One order, one approval request and PO per supplier", { placeholder: "title" });
  const colX = [M, 4.85, 9.35], colW = [3.45, 3.75, 3.38];
  ["Products in the request", "Approval requests · one per supplier", "Purchase orders · one per request"]
    .forEach((h, i) => text(s, h, { x: colX[i], y: TOP, w: colW[i], h: 0.4, fontSize: 15, bold: true, color: C.accent6 }));
  const prods = [
    ["100 x pressure sensor", "0-150 psi · 4-20 mA · 1/4\" NPT", "Best: WIKA A-10"],
    ["6 x magnetic flow meter", "2 in pipe · 4-20 mA", "Best: DwyerOmega FMG91"],
    ["200 x proximity sensor", "M18 · PNP · 8 mm · IP67", "Best: DwyerOmega PRX-M18-8P"],
  ];
  const py = [2.05, 3.4, 4.75], ph = 1.1;
  prods.forEach(([t, sub, best], i) => {
    card(s, colX[0], py[i], colW[0], ph, "Product " + (i + 1));
    text(s, t, { x: colX[0] + 0.2, y: py[i] + 0.12, w: colW[0] - 0.4, h: 0.35, fontSize: 16, bold: true, color: C.text2 });
    text(s, sub, { x: colX[0] + 0.2, y: py[i] + 0.47, w: colW[0] - 0.4, h: 0.3, fontSize: 13, color: C.accent6 });
    text(s, best, { x: colX[0] + 0.2, y: py[i] + 0.75, w: colW[0] - 0.4, h: 0.3, fontSize: 13, color: C.text1 });
  });
  // approval requests
  const reqs = [
    { y: py[0], h: ph, title: "Request 1 · WIKA", body: "1 product · 15,800 USD", fill: "FFF7ED" },
    { y: py[1], h: py[2] + ph - py[1], title: "Request 2 · DwyerOmega", body: "2 products · 13,540 USD\nFlow meters and proximity sensors together", fill: "FFF7ED" },
  ];
  reqs.forEach((r, i) => {
    card(s, colX[1], r.y, colW[1], r.h, "Approval request " + (i + 1), r.fill);
    icon(s, "FaUserCheck", colX[1] + 0.2, r.y + 0.2, 0.55, C.accent4, "Request " + (i + 1));
    text(s, r.title, { x: colX[1] + 0.9, y: r.y + 0.2, w: colW[1] - 1.05, h: 0.55, fontSize: 17, bold: true,
      color: C.text2, valign: "middle" });
    text(s, r.body, { x: colX[1] + 0.2, y: r.y + 0.8, w: colW[1] - 0.4, h: r.h - 0.9, fontSize: 14 });
  });
  const pos = [
    { y: py[0], h: ph, title: "PO-2026-0001 · WIKA", body: "1 line · 15,800 USD" },
    { y: py[1], h: py[2] + ph - py[1], title: "PO-2026-0002 · DwyerOmega", body: "2 lines · 13,540 USD\nOne PDF with both models" },
  ];
  pos.forEach((r, i) => {
    card(s, colX[2], r.y, colW[2], r.h, "Purchase order " + (i + 1), "ECFDF5");
    icon(s, "FaFileInvoice", colX[2] + 0.2, r.y + 0.2, 0.55, C.accent3, "PO " + (i + 1));
    text(s, r.title, { x: colX[2] + 0.9, y: r.y + 0.2, w: colW[2] - 1.05, h: 0.55, fontSize: 15, bold: true,
      color: C.text2, valign: "middle" });
    text(s, r.body, { x: colX[2] + 0.2, y: r.y + 0.8, w: colW[2] - 0.4, h: r.h - 0.9, fontSize: 14 });
  });
  const mid2 = py[1] + (py[2] + ph - py[1]) / 2;
  arrow(s, colX[0] + colW[0] + 0.05, py[0] + ph / 2, colX[1] - 0.05, py[0] + ph / 2, "Arrow P1 to R1");
  arrow(s, colX[0] + colW[0] + 0.05, py[1] + ph / 2, colX[1] - 0.05, mid2 - 0.15, "Arrow P2 to R2");
  arrow(s, colX[0] + colW[0] + 0.05, py[2] + ph / 2, colX[1] - 0.05, mid2 + 0.15, "Arrow P3 to R2");
  arrow(s, colX[1] + colW[1] + 0.05, py[0] + ph / 2, colX[2] - 0.05, py[0] + ph / 2, "Arrow R1 to PO1");
  arrow(s, colX[1] + colW[1] + 0.05, mid2, colX[2] - 0.05, mid2, "Arrow R2 to PO2");
  const rules = ["Same supplier → one request → one PO", "Each request approved or rejected on its own",
    "Supplier change only to one that quoted every part"];
  const rw = (CW - 2 * 0.3) / 3;
  rules.forEach((t, i) => {
    const x = M + i * (rw + 0.3);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 6.1, w: rw, h: 0.6, rectRadius: 0.1, fill: { color: C.background2 },
      line: { color: C.background2, width: 0 }, objectName: "Rule " + (i + 1) });
    text(s, t, { x: x + 0.15, y: 6.1, w: rw - 0.3, h: 0.6, fontSize: 14, bold: true, color: C.text2, valign: "middle",
      align: "center" });
  });
  s.addNotes("This is the main new idea. Three parts are needed. WIKA wins the pressure sensors; DwyerOmega wins " +
    "both the flow meters and the proximity sensors. So the requester submits once, and that creates two approval " +
    "requests, one per supplier. Each approved request becomes exactly one purchase order, and DwyerOmega's PO " +
    "carries both of its parts. If one supplier wins everything, there is one request and one PO. Prices are mocked.");

  // ============================================================= 5 Live demo
  pres.addSection({ title: "Demo" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Demo" });
  s.addText("Live demo: a rocket engine test stand", { placeholder: "title" });
  const demo = [
    "Requester clicks “Rocket test stand · 3 parts” and Extract details",
    "Confirm 3 products and their specs",
    "Watch the agent search 11 supplier catalogues",
    "Submit: 2 approval requests, one per supplier",
    "Approver is alerted, approves each, downloads 2 PDF POs",
  ];
  demo.forEach((t, i) => {
    const y = TOP + 0.15 + i * 1.0;
    numberDot(s, i + 1, M, y, 0.55, i >= 3 ? C.accent4 : C.accent1, "Demo step " + (i + 1));
    text(s, t, { x: M + 0.8, y: y - 0.1, w: 4.75, h: 0.75, fontSize: 16, valign: "middle" });
  });
  const iw = 6.35;
  const ih = picture(s, "agent_activity_top.png", W - M - iw, TOP + 0.05, iw, 1640, 1060, "Agent activity screenshot",
    "Live agent activity: searching five supplier catalogues for 100 pressure sensors, with spec requirements and the best model per supplier");
  text(s, "The live agent panel during the search. Backup screens are in the appendix.",
    { x: W - M - iw, y: TOP + 0.15 + ih, w: iw, h: 0.35, fontSize: 12, color: C.accent6 });
  s.addNotes("Demo, about 4 minutes. Before you start, open https://d1pr6lnlyeiqdc.cloudfront.net/proxy/8501/ in two " +
    "windows: requester madhukar.reddy@royalcyber.com and approver mreddy@dwyeromega.com, both with the demo password. " +
    "Requester: click the 'Rocket test stand · 3 parts' example, then Extract details. Type 'Rocket engine test " +
    "stand' as the title. Confirm and search suppliers: narrate the live panel, which shows each supplier site, how " +
    "many models fit, and why others do not. Show the plan: 2 approval requests, 2 purchase orders. Click Submit 2 " +
    "approval requests. Approver window: two alerts appear within 15 seconds without a reload. Approve the WIKA " +
    "request, then the DwyerOmega request, and download both PDFs. If the network or Bedrock fails, use the appendix.");

  // ============================================================= 6 Specs and ranking
  pres.addSection({ title: "Result" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Result" });
  s.addText("Every spec checked, every choice explained", { placeholder: "title" });
  s.addChart(pres.charts.BAR, [{ name: "Score", labels: ["Emerson", "Siemens", "Honeywell", "DwyerOmega", "WIKA"],
    values: [0, 66, 75, 97, 98] }], {
    x: M, y: TOP, w: 6.3, h: 4.6, barDir: "bar", objectName: "Pressure sensor score chart",
    chartColors: [HEX.accent6, HEX.accent6, HEX.accent6, HEX.accent6, HEX.accent3],
    showTitle: true, title: "100 pressure sensors: score of each supplier's best fitting model", titleFontFace: "+mn-lt",
    titleFontSize: 15, titleColor: C.text2,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontFace: "+mn-lt", dataLabelFontSize: 14,
    dataLabelColor: C.text1, catAxisLabelFontFace: "+mn-lt", catAxisLabelFontSize: 14, catAxisLabelColor: C.text1,
    valAxisLabelFontFace: "+mn-lt", valAxisLabelFontSize: 12, valAxisLabelColor: C.accent6,
    valAxisMaxVal: 100, valAxisMinVal: 0, valAxisMajorUnit: 25,
    valGridLine: { color: "E2E8F0", size: 1 }, catGridLine: { style: "none" }, showLegend: false, barGapWidthPct: 60,
  });
  text(s, "Score: on time first, then 60% price, 40% delivery. WIKA wins: in stock, 158 USD/unit. Honeywell is " +
    "cheaper (149 USD) but ships in 20 days. Prices are mocked.",
    { x: M, y: TOP + 4.7, w: 6.3, h: 0.7, fontSize: 12, color: C.accent6, italic: true });
  card(s, 7.3, TOP + 0.1, 5.43, 3.1, "Rejected models card", "FEF2F2");
  text(s, "5 of 12 models rejected, each with a reason", { x: 7.55, y: TOP + 0.3, w: 5.0, h: 0.45, fontSize: 18,
    bold: true, color: C.text2 });
  text(s, bullets([
    "DwyerOmega 626: range 0-100 psi, need 150",
    "Siemens P200: 0-10 bar is 145 psi, need 150",
    "Siemens P320: 1/2\" NPT, need 1/4\"",
    "Honeywell MLH150: 0.5-4.5 V, need 4-20 mA",
    "Emerson 2051TG: 1/2\" NPT, need 1/4\"",
  ]), { x: 7.55, y: TOP + 0.85, w: 5.0, h: 2.2, fontSize: 15 });
  icon(s, "FaRobot", 7.3, TOP + 3.6, 0.6, C.accent2, "Bedrock reads");
  text(s, "Bedrock reads the request and writes the summary.", { x: 8.1, y: TOP + 3.6, w: 4.63, h: 0.6,
    fontSize: 15, valign: "middle" });
  icon(s, "FaCogs", 7.3, TOP + 4.5, 0.6, C.text2, "Python decides");
  text(s, "Python converts units, checks specs and ranks. Winners never come from model text.",
    { x: 8.1, y: TOP + 4.5, w: 4.63, h: 0.75, fontSize: 15, valign: "middle" });
  s.addNotes("The pressure-sensor line from the demo. Five supplier catalogues, twelve models. Five models are rejected " +
    "with a reason the requester can read; note that 0-10 bar is converted to 145 psi before comparing. Among the " +
    "rest, WIKA scores 98: on time, in stock, 158 USD a unit. Honeywell is cheaper but ships in 20 days. The " +
    "approver sees all of this. Scores come from tested code, not from the model. All prices are mocked.");

  // ============================================================= 7 Human control
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Result" });
  s.addText("No order without a person, by design", { placeholder: "title" });
  const ctrl = [
    ["FaBan", C.accent5, "The AI cannot order",
      "The agent has two read-only tools. Calls to place_order, confirm_purchase and other order tools are refused."],
    ["FaUserCheck", C.accent4, "One decision per supplier request",
      "Approver role required, no self-approval, expired quotes blocked. Each request becomes exactly one PO."],
    ["FaExchangeAlt", C.accent1, "Supplier changes are controlled",
      "Only to a supplier that quoted every product in the request, and only with a written reason."],
    ["FaClipboardList", C.accent3, "Safe and recorded",
      "Eight approvers at once: one decision, one PO. Requests, alerts, decisions and PO numbers are audited."],
  ];
  const gw = (CW - 0.35) / 2;
  ctrl.forEach(([k, col, title, body], i) => {
    const x = M + (i % 2) * (gw + 0.35), y = TOP + 0.1 + Math.floor(i / 2) * 2.6;
    card(s, x, y, gw, 2.3, title + " card");
    icon(s, k, x + 0.3, y + 0.3, 0.75, col, title);
    text(s, title, { x: x + 1.3, y: y + 0.35, w: gw - 1.6, h: 0.65, fontSize: 21, bold: true, color: C.text2,
      valign: "middle" });
    text(s, body, { x: x + 0.3, y: y + 1.25, w: gw - 0.6, h: 0.95, fontSize: 16 });
  });
  s.addNotes("This is requirement BR-7.1. Every point is enforced in code and covered by tests, including the " +
    "concurrency test with eight simultaneous approvals and the rule that one request can never turn into two POs.");

  // ============================================================= 8 Result in hours and dollars
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Result" });
  s.addText("Result: minutes instead of an hour per request", { placeholder: "title" });
  [["40 min", "saved per request"], ["133 h", "saved per month"], ["~$80k", "saved per year"]].forEach(([n, l], i) => {
    const x = M + i * 4.13;
    text(s, n, { x, y: TOP + 0.05, w: 3.9, h: 1.1, fontSize: 60, bold: true, color: C.accent1, fontFace: "Cambria" });
    text(s, l, { x, y: TOP + 1.15, w: 3.9, h: 0.4, fontSize: 18, color: C.text1 });
  });
  text(s, "Estimate, not measured: 45 minutes of manual handling per request today, 5 minutes with the agent, " +
    "200 requests a month, USD 50 an hour. Replace with RoyalCyber's real volumes before relying on it.",
    { x: M, y: TOP + 1.7, w: CW, h: 0.6, fontSize: 12, color: C.accent6, italic: true });
  text(s, "Measured in this build", { x: M, y: 4.05, w: CW, h: 0.45, fontSize: 20, bold: true, color: C.text2 });
  const facts = [["292", "automated tests passing"], ["< 16 s", "to search 11 catalogues for 3 products (live: 13.5 s, 15.9 s)"],
    ["4", "Bedrock calls per request, 1 or 3 products"], ["0", "orders possible without approval in tests"]];
  const fw = (CW - 3 * 0.3) / 4;
  facts.forEach(([n, l], i) => {
    const x = M + i * (fw + 0.3);
    card(s, x, 4.65, fw, 1.85, "Fact " + (i + 1));
    text(s, n, { x: x + 0.25, y: 4.8, w: fw - 0.5, h: 0.8, fontSize: 40, bold: true, color: C.text2, fontFace: "Cambria" });
    text(s, l, { x: x + 0.25, y: 5.62, w: fw - 0.5, h: 0.8, fontSize: 15 });
  });
  s.addNotes("Top row is an estimate with its assumptions on screen: 40 minutes saved times 200 requests is about " +
    "133 hours a month, about 80,000 USD a year at 50 USD an hour. Bottom row is measured on 21 November: the " +
    "test suite; two live runs of the three-part request (13.5 and 15.9 seconds including simulated catalogue response times); " +
    "and the Bedrock call count, which stays at four because the model batches the tool calls.");

  // ============================================================= 9 Well-Architected
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Result" });
  s.addText("Well-Architected: what is in place", { placeholder: "title" });
  const pillars = [
    ["FaCogs", C.accent2, "Operational excellence", ["292 automated tests, including browser tests",
      "Audit log of requests, alerts, decisions and POs", "A failed alert or PO never loses a request",
      "Git history, setup and clean-up documented"]],
    ["FaShieldAlt", C.accent1, "Security", ["Separate requester and approver logins",
      "Salted scrypt passwords, lockout after 5 failures", "AI has no order or approval tools",
      "Model and supplier text escaped on screen", "No secrets in code, synthetic data only"]],
    ["FaDollarSign", C.accent3, "Cost optimization", ["Small model: Amazon Nova Lite",
      "4 Bedrock calls per request, even for 3 products", "Spec checks and ranking in plain Python",
      "Bedrock kept under 1 request per second", "No always-on cloud resources today"]],
  ];
  const pw = (CW - 2 * 0.35) / 3;
  pillars.forEach(([k, col, title, items], i) => {
    const x = M + i * (pw + 0.35);
    card(s, x, TOP + 0.1, pw, 4.1, title + " card");
    icon(s, k, x + 0.3, TOP + 0.35, 0.7, col, title);
    text(s, title, { x: x + 1.15, y: TOP + 0.35, w: pw - 1.35, h: 0.7, fontSize: 20, bold: true, color: C.text2,
      valign: "middle" });
    text(s, bullets(items), { x: x + 0.3, y: TOP + 1.3, w: pw - 0.55, h: 2.8, fontSize: 15 });
  });
  text(s, "Hackathon shortcuts to fix before a pilot: mocked supplier prices, local hosting, demo passwords, local file storage.",
    { x: M, y: 6.0, w: CW, h: 0.35, fontSize: 12, color: C.accent6, italic: true });
  s.addNotes("Three of the judged pillars. Be upfront about the shortcuts at the bottom: they are why the next slide " +
    "connects real supplier data and moves the app to AgentCore with Cognito and DynamoDB.");

  // ============================================================= 10 Next: AgentCore
  pres.addSection({ title: "Next steps" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Next steps" });
  s.addText("Next: run it on Amazon Bedrock AgentCore", { placeholder: "title" });
  const aw = 8.1;
  const ah = picture(s, "architecture.png", M, TOP, aw, 2610, 1605, "AgentCore architecture",
    "Target architecture: Streamlit, Cognito, AgentCore Runtime, Gateway with policy, Bedrock guardrails and Nova Lite, " +
    "tool Lambdas over the supplier catalogue, DynamoDB, approval API with one request and one PO per supplier, S3");
  text(s, "Full diagram: docs/architecture/agentcore-architecture.svg", { x: M, y: TOP + ah + 0.1, w: aw, h: 0.3,
    fontSize: 11, color: C.accent6 });
  const phases = [["Phase 1 · about 4 h", "AWS CDK base, Cognito logins, Guardrails, agent on AgentCore Runtime, approval API (one request and PO per supplier)"],
    ["Phase 2 · about 3 h", "AgentCore Gateway with Cedar policy, Memory, Observability, Evaluations"],
    ["Phase 3 · optional", "Knowledge Base for procurement policy documents"]];
  phases.forEach(([h, b], i) => {
    const y = TOP + 0.05 + i * 1.75;
    numberDot(s, i + 1, 9.0, y, 0.5, C.accent1, "Phase " + (i + 1) + " circle");
    text(s, h, { x: 9.7, y: y + 0.02, w: 3.03, h: 0.45, fontSize: 17, bold: true, color: C.text2 });
    text(s, b, { x: 9.7, y: y + 0.5, w: 3.03, h: 1.2, fontSize: 14 });
  });
  s.addNotes("The target follows the AWS AgentCore end-to-end blueprint, adapted to the hackathon rules: CDK instead " +
    "of Terraform, no third-party services, and the agent still has no write tools. The approval API keeps today's " +
    "rule: one approval request and one PO per supplier.");

  // ============================================================= 11 Close
  s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Next steps" });
  s.addText("Next steps", { placeholder: "title" });
  const asks = [["FaPlug", C.accent2, "Real supplier data", "Distributor APIs or RFQ emails behind the same search tool."],
    ["FaCloud", C.accent4, "Approve phase 1", "Deploy on AgentCore with AWS CDK in us-east-1, about 4 hours."],
    ["FaClock", C.accent3, "Pilot with real volumes", "Measure real handling time to replace the estimated savings."]];
  const kw = (CW - 2 * 0.35) / 3;
  asks.forEach(([k, col, title, body], i) => {
    const x = M + i * (kw + 0.35);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.75, w: kw, h: 3.0, rectRadius: 0.12,
      fill: { color: C.background1, transparency: 88 }, line: { color: C.background1, width: 0, transparency: 100 },
      objectName: title + " card" });
    icon(s, k, x + 0.35, 2.05, 0.8, col, title);
    text(s, title, { x: x + 0.35, y: 3.05, w: kw - 0.7, h: 0.55, fontSize: 22, bold: true, color: C.background1 });
    text(s, body, { x: x + 0.35, y: 3.65, w: kw - 0.7, h: 1.0, fontSize: 16, color: C.background2 });
  });
  text(s, "Thank you. Questions?", { x: M, y: 5.45, w: CW, h: 0.8, fontSize: 32, bold: true, color: C.background1,
    fontFace: "Cambria" });
  text(s, "Code, tests and design: /workshop (git). Supplier names are real; prices, stock and lead times are mocked.",
    { x: M, y: 6.35, w: CW, h: 0.4, fontSize: 14, color: C.background2 });
  s.addNotes("Close on the three asks, then take questions. If time is short, go straight here after the demo.");

  // ============================================================= Appendix
  pres.addSection({ title: "Appendix: demo backup" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Appendix: demo backup" });
  s.addText("Backup: the requester's plan and submission", { placeholder: "title" });
  const bw = 10.5, bx = (W - bw) / 2;
  const h1 = picture(s, "po_plan.png", bx, TOP, bw, 1640, 558, "PO plan screenshot",
    "Plan: 2 approval requests and 2 purchase orders, WIKA for pressure sensors and DwyerOmega for flow meters and proximity sensors, total 29,340 USD");
  picture(s, "submitted.png", bx, TOP + h1 + 0.25, bw, 1576, 146, "Submitted screenshot",
    "Confirmation: 2 approval requests submitted, one per supplier");
  s.addNotes("Use if the live demo fails. Same request: three parts for a rocket engine test stand.");

  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Appendix: demo backup" });
  s.addText("Backup: approver alerts, decision and PO", { placeholder: "title" });
  const lw = 7.0;
  const ha = picture(s, "approver_alerts.png", M, TOP + 0.05, lw, 1640, 416, "Approver alerts screenshot",
    "Two alerts: one approval request for WIKA and one for DwyerOmega");
  const hd = picture(s, "approver_decision.png", M, TOP + 0.05 + ha + 0.2, lw, 1736, 494, "Approver decision screenshot",
    "Decision panel: one supplier for all 2 products, approve issues 1 purchase order");
  text(s, "Each request is decided on its own and becomes one PO.", { x: M, y: TOP + 0.15 + ha + 0.2 + hd, w: lw,
    h: 0.35, fontSize: 12, color: C.accent6 });
  const pdfH = 4.75, pdfW = pdfH * 1191 / 1111;
  s.addImage({ path: asset("po_pdf.png"), x: W - M - pdfW, y: TOP + 0.05, w: pdfW, h: pdfH, objectName: "PO PDF",
    altText: "PDF purchase order PO-2026-0002 to DwyerOmega with two lines, RoyalCyber as buyer" });
  text(s, "PO-2026-0002: one PDF, two lines", { x: W - M - pdfW, y: TOP + 0.15 + pdfH, w: pdfW, h: 0.35,
    fontSize: 12, color: C.accent6 });
  s.addNotes("Use if the live demo fails: the two alerts, the decision panel for the DwyerOmega request, and the PDF " +
    "purchase order it produced with both of its parts.");

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
