/**
 * 백엔드 API 주소.
 *
 * - 로컬 개발: 아래 기본값(http://127.0.0.1:8000)이 그대로 쓰인다.
 * - Vercel 배포: 빌드 시 build.js 가 환경 변수 API_BASE_URL 값으로 이 파일을 덮어쓴다.
 *   (Vercel 대시보드 > Settings > Environment Variables 에 API_BASE_URL 등록)
 */
window.APP_CONFIG = {
  API_BASE_URL: "http://127.0.0.1:8000",
};
