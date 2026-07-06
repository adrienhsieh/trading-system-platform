const fs = require("fs");
const path = require("path");

const routes = JSON.parse(fs.readFileSync("routes.json", "utf-8"));
const baseDir = "D:/SourceCode/Web/Python/trading-system-upgrade/static/js";

function fixFile(filePath) {
  let content = fs.readFileSync(filePath, "utf-8");
  routes.forEach(route => {
    // 假設原本是 /api/prediction/test，要改成 /api/predict/test
    content = content.replace(/\/api\/prediction\/test/g, "/api/predict/test");
    content = content.replace(/\/api\/prediction\/stream/g, "/api/predict/stream");
  });
  fs.writeFileSync(filePath, content, "utf-8");
  console.log("已修正:", filePath);
}

fs.readdirSync(baseDir).forEach(file => {
  if (file.endsWith(".js")) {
    fixFile(path.join(baseDir, file));
  }
});
