/**
 * Vercel 빌드 시 실행된다.
 * 환경 변수 API_BASE_URL 값을 읽어 config.js 를 생성한다.
 * -> API 주소를 코드에 하드코딩하지 않고 환경 변수로 관리할 수 있다.
 */
const fs = require("fs");

const apiBaseUrl = (process.env.API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

const content = `// 이 파일은 build.js 가 자동 생성합니다. 직접 수정하지 마세요.
window.APP_CONFIG = {
  API_BASE_URL: ${JSON.stringify(apiBaseUrl)},
};
`;

fs.writeFileSync("config.js", content, "utf-8");
console.log(`[build] config.js 생성 완료 -> API_BASE_URL = ${apiBaseUrl}`);
