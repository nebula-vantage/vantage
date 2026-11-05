Vantage's bundled web fonts

These fonts match the families named by ios/VantageMobile/DesignSystem/Theme.swift.
They are redistributed under the SIL Open Font License, Version 1.1. Full license
and copyright notices are included in this directory, separately for each family.

Upstream: the official Google Fonts repository, https://github.com/google/fonts

Bricolage Grotesque:
  ofl/bricolagegrotesque/BricolageGrotesque[opsz,wdth,wght].ttf
  Weights 200-800; optical size 12-96; width 75-100.
  License: bricolagegrotesque-OFL.txt

IBM Plex Sans:
  ofl/ibmplexsans/IBMPlexSans[wdth,wght].ttf
  Weights 100-700; width 75-100.
  License: ibmplexsans-OFL.txt

IBM Plex Mono:
  ofl/ibmplexmono/IBMPlexMono-Regular.ttf (400)
  ofl/ibmplexmono/IBMPlexMono-Medium.ttf (500)
  License: ibmplexmono-OFL.txt

The upstream TTF files were losslessly packaged as WOFF2 using fontTools. Glyphs
were not subsetted and font naming/design data was not intentionally changed.
The browser loads these local files using ../fonts.css; no font CDN is required.
