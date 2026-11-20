// Builds docs/presentation/Intelligent-Procurement-Agent.pptx
// Run from anywhere:  node docs/presentation/build_deck.js
// Uses the Kiro pptx skill (.kiro/skills/pptx): pptxgenjs + apply_theme.js.
// All figures come from the repository (tests, measurements, docs) except the
// clearly labelled savings estimate on the Result slide.
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

// Palette matches the app's UI so the screenshots sit naturally in the deck:
// midnight navy dominates, indigo for the agent, orange marks the human approval step.
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
  pres.subject = "Hackathon demo, 20 November 2026";
  const C = pres.SchemeColor;

  const ICON = {};
  for (const n of ["FaShoppingCart", "FaRobot", "FaBalanceScale", "FaUserCheck", "FaFileInvoice", "FaUser",
    "FaUserTie", "FaEnvelopeOpenText", "FaTable", "FaInbox", "FaQuestionCircle", "FaShieldAlt", "FaLock",
    "FaCogs", "FaDollarSign", "FaClock", "FaBell", "FaCloud", "FaBan", "FaClipboardList"]) {
    ICON[n] = await iconPng(fa[n]);
  }

  // ------------------------------------------------------------- layouts
  pres.defineSlideMaster({
    title: "TITLE_DARK",
    background: { color: C.text2 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 1.3, w: 11.7, h: 1.5,
        fontSize: 48, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "subtitle", type: "body", x: 0.8, y: 2.95, w: 11.0, h: 1.0,
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
      { text: { text: "Intelligent Procurement Agent · RoyalCyber · synthetic demo data",
        options: { x: M, y: 7.0, w: 9.0, h: 0.3, fontSize: 10, color: C.accent6, margin: 0 } } },
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

  // ============================================================= 1 Title
  pres.addSection({ title: "Introduction" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction" });
  s.addText("Intelligent Procurement Agent", { placeholder: "title" });
  s.addText("From a plain-English purchase request to an approved purchase order, with a person in control",
    { placeholder: "subtitle" });
  s.addText("RoyalCyber · Hackathon demo · 20 November 2026 · Amazon Bedrock (us-east-1)", { placeholder: "meta" });
  const flow = [["FaShoppingCart", "Ask", C.accent2], ["FaRobot", "Extract", C.accent1],
    ["FaBalanceScale", "Compare", C.accent1], ["FaUserCheck", "Approve", C.accent4], ["FaFileInvoice", "Order", C.accent3]];
  flow.forEach(([k, label, col], i) => {
    const x = 0.8 + i * 1.75;
    icon(s, k, x, 4.55, 0.9, col, label);
    text(s, label, { x: x - 0.25, y: 5.55, w: 1.4, h: 0.4, fontSize: 16, bold: true, color: C.background1,
      align: "center" });
  });
  s.addNotes("Introduce the team and the one-line pitch: requesters ask in plain English, the agent finds and " +
    "compares supplier quotes, and nothing is ordered until an approver signs off. The five icons are the flow " +
    "we will demo.");

  // ============================================================= 2 Problem
  pres.addSection({ title: "Problem" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Problem" });
  s.addText("Buying today runs on email and spreadsheets", { placeholder: "title" });
  const personas = [
    ["FaUser", C.accent1, "Requester",
      "Needs 50 laptops by 15 December. Emails procurement, then waits without knowing which supplier was " +
      "picked or why."],
    ["FaUserTie", C.accent4, "Approver",
      "Gets requests by email with no side-by-side comparison, and approves from memory. Nothing records the " +
      "decision."],
  ];
  personas.forEach(([k, col, who, body], i) => {
    const y = TOP + 0.1 + i * 2.6;
    card(s, M, y, 5.6, 2.3, who + " card");
    icon(s, k, M + 0.3, y + 0.3, 0.75, col, who);
    text(s, who, { x: M + 1.25, y: y + 0.38, w: 4.0, h: 0.5, fontSize: 22, bold: true, color: C.text2 });
    text(s, body, { x: M + 0.3, y: y + 1.2, w: 5.0, h: 1.0, fontSize: 16 });
  });
  text(s, "What goes wrong today", { x: 6.9, y: TOP + 0.15, w: 5.8, h: 0.5, fontSize: 22, bold: true,
    color: C.text2 });
  [["FaEnvelopeOpenText", "Free-text requests are retyped by hand"],
    ["FaTable", "Quotes are compared in spreadsheets, one supplier at a time"],
    ["FaInbox", "Approvals sit in inboxes while delivery deadlines slip"],
    ["FaQuestionCircle", "No record of why a supplier won"]].forEach(([k, t], i) => {
    const y = TOP + 0.95 + i * 1.12;
    icon(s, k, 6.9, y, 0.62, C.accent6, "Problem " + (i + 1));
    text(s, t, { x: 7.8, y: y + 0.02, w: 4.9, h: 0.62, fontSize: 18, valign: "middle" });
  });
  s.addNotes("Who has the problem: requesters who need goods by a date, and approvers who sign off spend. " +
    "Today requests arrive as free text, quotes are compared by hand, and approvals have no trail. " +
    "Keep this under a minute.");

  // ============================================================= 3 How it works
  pres.addSection({ title: "Solution" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Solution" });
  s.addText("Five steps from request to purchase order", { placeholder: "title" });
  const steps = [
    ["FaShoppingCart", C.accent2, "1  Ask", "The requester types the need in plain English, or picks an example."],
    ["FaRobot", C.accent1, "2  Extract", "Bedrock reads product, quantity and date. Missing details are asked for, never guessed."],
    ["FaBalanceScale", C.accent1, "3  Compare", "On-time suppliers rank first, then 60% price and 40% delivery."],
    ["FaUserCheck", C.accent4, "4  Approve", "Approvers are alerted. They approve, reject, or pick another supplier with a reason."],
    ["FaFileInvoice", C.accent3, "5  Order", "A numbered PDF purchase order is issued, with RoyalCyber as buyer."],
  ];
  const sw = 2.25, sg = (CW - 5 * sw) / 4;
  steps.forEach(([k, col, title, body], i) => {
    const x = M + i * (sw + sg);
    card(s, x, TOP + 0.1, sw, 3.45, "Step " + (i + 1) + " card");
    icon(s, k, x + 0.25, TOP + 0.35, 0.75, col, "Step " + (i + 1));
    text(s, title, { x: x + 0.25, y: TOP + 1.3, w: sw - 0.4, h: 0.45, fontSize: 20, bold: true, color: C.text2 });
    text(s, body, { x: x + 0.25, y: TOP + 1.85, w: sw - 0.4, h: 1.6, fontSize: 15 });
  });
  icon(s, "FaRobot", M, 5.5, 0.6, C.accent2, "Bedrock role");
  text(s, "Amazon Bedrock (Nova Lite) reads the request and writes the explanation.",
    { x: M + 0.8, y: 5.5, w: 5.1, h: 0.85, fontSize: 16, valign: "middle" });
  icon(s, "FaLock", 6.75, 5.5, 0.6, C.text2, "App role");
  text(s, "Python ranks quotes, enforces approval and issues the PO. The AI has no tool that can order.",
    { x: 7.55, y: 5.5, w: 5.18, h: 0.85, fontSize: 16, valign: "middle" });
  s.addNotes("Walk the five steps left to right. Stress the split at the bottom: the model handles language, " +
    "ordinary code makes every decision that matters, and step 4 is always a person.");

  // ============================================================= 4 Live demo
  pres.addSection({ title: "Demo" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Demo" });
  s.addText("Live demo: one request, end to end", { placeholder: "title" });
  const demo = [
    "Sign in as the requester, madhukar.reddy@royalcyber.com",
    "Type “I need 50 laptops delivered by December 15”",
    "Confirm the details and review the recommendation",
    "Submit. The approver mreddy@dwyeromega.com is alerted within 15 seconds",
    "Approve and download the PDF purchase order",
  ];
  demo.forEach((t, i) => {
    const y = TOP + 0.15 + i * 1.0;
    const dc = i >= 3 ? C.accent4 : C.accent1;
    s.addShape(pres.shapes.OVAL, { x: M, y, w: 0.55, h: 0.55, fill: { color: dc },
      line: { color: dc, width: 0 }, objectName: "Demo step " + (i + 1) + " circle" });
    text(s, String(i + 1), { x: M, y, w: 0.55, h: 0.55, fontSize: 18, bold: true, color: C.background1,
      align: "center", valign: "middle" });
    text(s, t, { x: M + 0.8, y: y - 0.1, w: 4.65, h: 0.75, fontSize: 16, valign: "middle" });
  });
  const rw = 6.45, rh = rw * 570 / 1020;
  s.addImage({ path: path.join(ASSETS, "recommendation.png"), x: W - M - rw, y: TOP + 0.1, w: rw, h: rh,
    objectName: "Recommendation screenshot",
    altText: "App screenshot: Acme Supplies recommended, 47,500 USD, on time, with the Bedrock explanation" });
  text(s, "Screenshot of the running app. Backup screens are in the appendix.",
    { x: W - M - rw, y: TOP + 0.25 + rh, w: rw, h: 0.35, fontSize: 12, color: C.accent6 });
  s.addNotes("Demo, about 4 minutes. Open https://d1pr6lnlyeiqdc.cloudfront.net/proxy/8501/ in two windows " +
    "before you start: requester madhukar.reddy@royalcyber.com and approver mreddy@dwyeromega.com, both with " +
    "the demo password. Requester: click the '50 laptops by Dec 15' example, Extract details, Confirm and get " +
    "quotes. Point out the winner card, the Bedrock explanation and the delivery-vs-deadline chart. Submit. " +
    "Switch to the approver window: the alert appears within 15 seconds without a reload. Approve, then " +
    "download the PDF. If the network or Bedrock fails, use the appendix screenshots.");

  // ============================================================= 5 Bedrock explains, app decides
  pres.addSection({ title: "Result" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Result" });
  s.addText("Bedrock explains; the app decides", { placeholder: "title" });
  s.addChart(pres.charts.BAR, [{ name: "Total price (USD)", labels: ["QuickShip Ltd", "Acme Supplies", "TechWorld"],
    values: [51000, 47500, 44950] }], {
    x: M, y: TOP, w: 6.9, h: 5.1, barDir: "bar", objectName: "Total price chart",
    chartColors: [HEX.accent6, HEX.accent3, HEX.accent6],
    showTitle: true, title: "Total price for 50 laptops (USD)", titleFontFace: "+mn-lt", titleFontSize: 16,
    titleColor: C.text2,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "#,##0", dataLabelFontFace: "+mn-lt",
    dataLabelFontSize: 14, dataLabelColor: C.text1,
    catAxisLabelFontFace: "+mn-lt", catAxisLabelFontSize: 14, catAxisLabelColor: C.text1,
    valAxisLabelFontFace: "+mn-lt", valAxisLabelFontSize: 12, valAxisLabelColor: C.accent6,
    valAxisLabelFormatCode: "#,##0", valAxisMaxVal: 60000, valAxisMinVal: 0,
    valGridLine: { color: "E2E8F0", size: 1 }, catGridLine: { style: "none" }, showLegend: false, barGapWidthPct: 60,
  });
  card(s, 7.85, TOP + 0.1, 4.88, 2.55, "Winner card", "ECFDF5");
  text(s, "Recommended: Acme Supplies", { x: 8.15, y: TOP + 0.3, w: 4.4, h: 0.5, fontSize: 20, bold: true,
    color: C.text2 });
  text(s, bullets(["Score 62 / 100, on time, 15 days early",
    "Costs 2,550 USD more than TechWorld and delivers 11 days earlier",
    "OldDeals Inc excluded: its quote had expired"]),
    { x: 8.15, y: TOP + 0.9, w: 4.4, h: 1.7, fontSize: 15 });
  icon(s, "FaRobot", 7.85, 4.45, 0.6, C.accent2, "Bedrock decides nothing");
  text(s, "Bedrock picks the tools and writes the explanation.", { x: 8.65, y: 4.45, w: 4.08, h: 0.65,
    fontSize: 15, valign: "middle" });
  icon(s, "FaCogs", 7.85, 5.4, 0.6, C.text2, "Python decides");
  text(s, "Python filters, scores and ranks. The winner is never taken from model text.",
    { x: 8.65, y: 5.4, w: 4.08, h: 0.75, fontSize: 15, valign: "middle" });
  s.addNotes("Acme is not the cheapest. TechWorld is 2,550 USD cheaper, but Acme delivers 11 days earlier, and " +
    "with the 60/40 weighting it scores 62 against 60. That trade-off is shown to the approver, who can still " +
    "pick TechWorld with a reason. Scores come from tested code, not the model.");

  // ============================================================= 6 Human control
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Result" });
  s.addText("No order without a person, by design", { placeholder: "title" });
  const ctrl = [
    ["FaBan", C.accent5, "The AI cannot order",
      "The agent has two read-only tools. Calls to place_order, confirm_purchase and three other order tools are refused."],
    ["FaUserCheck", C.accent4, "A person must approve",
      "Approver role required. No self-approval, expired quotes blocked, and a reason for any rejection or change of supplier."],
    ["FaLock", C.accent1, "One decision per case",
      "Eight approvers acting at once: exactly one decision is accepted and one PO is issued."],
    ["FaClipboardList", C.accent3, "Every step is recorded",
      "Submissions, alerts, decisions, refusals and PO numbers are written to an audit log."],
  ];
  const gw = (CW - 0.35) / 2;
  ctrl.forEach(([k, col, title, body], i) => {
    const x = M + (i % 2) * (gw + 0.35), y = TOP + 0.1 + Math.floor(i / 2) * 2.6;
    card(s, x, y, gw, 2.3, title + " card");
    icon(s, k, x + 0.3, y + 0.3, 0.75, col, title);
    text(s, title, { x: x + 1.3, y: y + 0.35, w: gw - 1.6, h: 0.65, fontSize: 22, bold: true, color: C.text2,
      valign: "middle" });
    text(s, body, { x: x + 0.3, y: y + 1.25, w: gw - 0.6, h: 0.95, fontSize: 16 });
  });
  s.addNotes("This is requirement BR-7.1. Each point is enforced in code and covered by tests, including the " +
    "concurrency test with eight simultaneous approvals.");

  // ============================================================= 7 Result in hours and dollars
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Result" });
  s.addText("Result: minutes instead of an hour per request", { placeholder: "title" });
  [["40 min", "saved per request"], ["133 h", "saved per month"], ["~$80k", "saved per year"]].forEach(([n, l], i) => {
    const x = M + i * 4.13;
    text(s, n, { x, y: TOP + 0.05, w: 3.9, h: 1.1, fontSize: 60, bold: true, color: C.accent1,
      fontFace: "Cambria" });
    text(s, l, { x, y: TOP + 1.15, w: 3.9, h: 0.4, fontSize: 18, color: C.text1 });
  });
  text(s, "Estimate, not measured: 45 minutes of manual handling per request today, 5 minutes with the agent, " +
    "200 requests a month, USD 50 an hour. Replace with RoyalCyber's real volumes before relying on it.",
    { x: M, y: TOP + 1.7, w: CW, h: 0.6, fontSize: 12, color: C.accent6, italic: true });
  text(s, "Measured in this build", { x: M, y: 4.05, w: CW, h: 0.45, fontSize: 20, bold: true, color: C.text2 });
  const facts = [["247", "automated tests passing"], ["3.3 s", "from submit to approver alert"],
    ["4", "Bedrock calls per request, 1.2 s apart"], ["0", "orders possible without approval in tests"]];
  const fw = (CW - 3 * 0.3) / 4;
  facts.forEach(([n, l], i) => {
    const x = M + i * (fw + 0.3);
    card(s, x, 4.65, fw, 1.85, "Fact " + (i + 1));
    text(s, n, { x: x + 0.25, y: 4.8, w: fw - 0.5, h: 0.8, fontSize: 40, bold: true, color: C.text2,
      fontFace: "Cambria" });
    text(s, l, { x: x + 0.25, y: 5.62, w: fw - 0.5, h: 0.8, fontSize: 15 });
  });
  s.addNotes("The top row is an estimate with the assumptions on screen: 40 minutes saved times 200 requests is " +
    "about 133 hours a month, about 80,000 USD a year at 50 USD an hour. The bottom row is measured: the test " +
    "suite, the alert latency from a browser test, and the Bedrock call pattern.");

  // ============================================================= 8 Well-Architected
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Result" });
  s.addText("Well-Architected: what is in place", { placeholder: "title" });
  const pillars = [
    ["FaCogs", C.accent2, "Operational excellence", ["247 automated tests, including browser tests",
      "Audit log of requests, decisions and alerts", "A failed alert or PO never loses a request",
      "Git history, setup and clean-up documented"]],
    ["FaShieldAlt", C.accent1, "Security", ["Separate requester and approver logins",
      "Salted scrypt passwords, lockout after 5 failures", "AI has no order or approval tools",
      "Model and supplier text escaped on screen", "No secrets in code, synthetic data only"]],
    ["FaDollarSign", C.accent3, "Cost optimization", ["Small model: Amazon Nova Lite",
      "4 calls per request, at most 1,024 output tokens", "Bedrock kept under 1 request per second",
      "No always-on cloud resources today", "Target design is pay-per-use"]],
  ];
  const pw = (CW - 2 * 0.35) / 3;
  pillars.forEach(([k, col, title, items], i) => {
    const x = M + i * (pw + 0.35);
    card(s, x, TOP + 0.1, pw, 4.1, title + " card");
    icon(s, k, x + 0.3, TOP + 0.35, 0.7, col, title);
    text(s, title, { x: x + 1.15, y: TOP + 0.35, w: pw - 1.35, h: 0.7, fontSize: 20, bold: true, color: C.text2,
      valign: "middle" });
    text(s, bullets(items), { x: x + 0.3, y: TOP + 1.3, w: pw - 0.55, h: 3.45, fontSize: 15 });
  });
  text(s, "Hackathon shortcuts to fix before a pilot: local hosting, demo passwords, local file storage.",
    { x: M, y: 6.0, w: CW, h: 0.35, fontSize: 12, color: C.accent6, italic: true });
  s.addNotes("Three of the judged pillars. Be upfront about the shortcuts at the bottom: they are why the next " +
    "slide moves the app to AgentCore with Cognito and DynamoDB.");

  // ============================================================= 9 Next: AgentCore
  pres.addSection({ title: "Next steps" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Next steps" });
  s.addText("Next: run it on Amazon Bedrock AgentCore", { placeholder: "title" });
  const aw = 8.1, ah = aw * 1605 / 2610;
  s.addImage({ path: path.join(ASSETS, "architecture.png"), x: M, y: TOP, w: aw, h: ah,
    objectName: "AgentCore architecture",
    altText: "Target architecture: Streamlit, Cognito, AgentCore Runtime, Gateway with policy, Bedrock guardrails " +
      "and Nova Lite, tool Lambdas, DynamoDB, approval API, S3 purchase orders" });
  text(s, "Full diagram: docs/architecture/agentcore-architecture.svg", { x: M, y: TOP + ah + 0.1, w: aw, h: 0.3,
    fontSize: 11, color: C.accent6 });
  const phases = [["Phase 1 · about 4 h", "AWS CDK base, Cognito logins, Bedrock Guardrails, agent on AgentCore Runtime, approval API"],
    ["Phase 2 · about 3 h", "AgentCore Gateway with Cedar policy, Memory, Observability, Evaluations"],
    ["Phase 3 · optional", "Knowledge Base for procurement policy documents"]];
  phases.forEach(([h, b], i) => {
    const y = TOP + 0.05 + i * 1.75;
    s.addShape(pres.shapes.OVAL, { x: 9.0, y, w: 0.5, h: 0.5, fill: { color: C.accent1 },
      line: { color: C.accent1, width: 0 }, objectName: "Phase " + (i + 1) + " circle" });
    text(s, String(i + 1), { x: 9.0, y, w: 0.5, h: 0.5, fontSize: 16, bold: true, color: C.background1,
      align: "center", valign: "middle" });
    text(s, h, { x: 9.7, y: y + 0.02, w: 3.03, h: 0.45, fontSize: 17, bold: true, color: C.text2 });
    text(s, b, { x: 9.7, y: y + 0.5, w: 3.03, h: 1.15, fontSize: 14 });
  });
  s.addNotes("The target follows the AWS AgentCore end-to-end blueprint, adapted to the hackathon rules: CDK " +
    "instead of Terraform, no third-party services, and the agent still has no write tools. Phase 1 is what we " +
    "would ship first.");

  // ============================================================= 10 Close
  s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Next steps" });
  s.addText("Next steps", { placeholder: "title" });
  const asks = [["FaCloud", C.accent2, "Approve phase 1", "Deploy with AWS CDK in us-east-1, about 4 hours of work."],
    ["FaBell", C.accent4, "Turn on email alerts", "Create the SNS topic and subscribe the approvers."],
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
  text(s, "Code, tests and design: /workshop (git). Demo data is synthetic.", { x: M, y: 6.35, w: CW, h: 0.4,
    fontSize: 14, color: C.background2 });
  s.addNotes("Close on the three asks, then take questions. If time is short, skip straight to this slide after " +
    "the demo.");

  // ============================================================= Appendix
  pres.addSection({ title: "Appendix: demo backup" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Appendix: demo backup" });
  s.addText("Backup: the requester's recommendation", { placeholder: "title" });
  const bh = 5.15, bw = bh * 1020 / 570;
  s.addImage({ path: path.join(ASSETS, "recommendation.png"), x: (W - bw) / 2, y: TOP, w: bw, h: bh,
    objectName: "Backup recommendation screenshot",
    altText: "Recommendation screen: Acme Supplies, score 62, total 47,500 USD, delivery 2026-11-30" });
  s.addNotes("Use if the live demo fails. Same request: 50 laptops by 15 December.");

  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Appendix: demo backup" });
  s.addText("Backup: approver alert and purchase order", { placeholder: "title" });
  const bh2 = 4.15, lw = bh2 * 1440 / 900, pw2 = bh2 * 1191 / 930;
  s.addImage({ path: path.join(ASSETS, "approver_alert.png"), x: M, y: TOP + 0.1, w: lw, h: bh2,
    objectName: "Approver alert screenshot", altText: "Approver workspace showing a new-request alert and pop-up" });
  text(s, "Approver alerted without reloading the page", { x: M, y: TOP + 0.25 + bh2, w: lw, h: 0.35,
    fontSize: 12, color: C.accent6 });
  s.addImage({ path: path.join(ASSETS, "po_pdf.png"), x: W - M - pw2, y: TOP + 0.1, w: pw2, h: bh2,
    objectName: "Purchase order PDF", altText: "PDF purchase order PO-2026-0001 with RoyalCyber as buyer" });
  text(s, "Generated PDF purchase order, RoyalCyber as buyer", { x: W - M - pw2, y: TOP + 0.25 + bh2, w: pw2,
    h: 0.35, fontSize: 12, color: C.accent6 });
  s.addNotes("Use if the live demo fails: the approver's alert, then the PDF purchase order that approval produces.");

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
