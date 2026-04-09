/**
 * Data URL логотипов источников (inline SVG).
 * При необходимости замените на импорт файлов из assets/sources/*.svg
 */
function svgToDataUrl(svg) {
  return 'data:image/svg+xml,' + encodeURIComponent(svg)
}

const headhunterSvg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24"><circle cx="12" cy="12" r="11" fill="#d63638"/><text x="12" y="16" text-anchor="middle" fill="white" font-family="Arial,sans-serif" font-size="11" font-weight="bold">hh</text></svg>'
const habrCareerSvg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24"><circle cx="12" cy="12" r="11" fill="#0dcaf0"/><text x="12" y="16" text-anchor="middle" fill="white" font-family="Arial,sans-serif" font-size="10" font-weight="bold">HC</text></svg>'
const superjobSvg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24"><circle cx="12" cy="12" r="11" fill="#198754"/><text x="12" y="16" text-anchor="middle" fill="white" font-family="Arial,sans-serif" font-size="10" font-weight="bold">SJ</text></svg>'

export const sourceLogoUrls = {
  headhunter: svgToDataUrl(headhunterSvg),
  habr_career: svgToDataUrl(habrCareerSvg),
  superjob: svgToDataUrl(superjobSvg)
}

export function getSourceLogoUrl(sourceKey) {
  return sourceLogoUrls[sourceKey] || null
}
