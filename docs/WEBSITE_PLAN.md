# Preen website plan

**Status: proposal only.** This document plans a website; no website, domain,
hosting, release-download service or analytics setup is implemented here. The
site should explain the actual desktop app and send people to verified source,
documentation and release assets.

## Goals and guardrails

- Give a new visitor a clear answer to “What is Preen?” and a safe path to try it.
- Feel like a refined macOS system utility: quiet, orderly, native and precise,
  without copying Apple branding, icons or proprietary artwork.
- Use **no gradients anywhere**: no gradient backgrounds, text, buttons, image
  overlays or borders. Use solid colours, thin borders and restrained shadows.
- Keep the site fast, accessible and readable without JavaScript. Do not invent
  download counts, testimonials, ratings, endorsements, supported platforms,
  release assets or features.
- Keep the current desktop app's [privacy policy](../PRIVACY.md) separate from
  the future site's actual hosting and data practices.

## Visual direction

| Element | Proposed treatment |
|---|---|
| Layout | Centred content, maximum width around 1,120 px, generous whitespace and an 8 px spacing grid. Desktop hero uses two columns; stack naturally on small screens. |
| Typography | System UI font stack, strong but restrained headings, comfortable line length and left-aligned text. No remote font service required. |
| Light theme | Warm near-white canvas `#F7F7F5`, white cards, `#1D1D1F` primary text, `#6E6E73` secondary text and subtle solid borders. |
| Dark theme | Reuse Preen's palette: `#202124` canvas, `#1B1C1E` sidebar, `#282A2D` surfaces, `#303236` elevated surfaces, `#F1F3F4` text, `#A5A9B0` secondary text, `#3B3E42` borders and `#3584E4` accent. |
| Controls | Solid blue or neutral buttons, 8–12 px corner radii, visible focus rings and at least 44×44 px targets. Use contrast-tested text; for example white on `#1C5EAF`, not white on `#3584E4` for small button text. |
| Imagery | Use the two real, approved screenshots in `docs/images/`, framed by a simple solid window border. Keep captions and descriptive alt text; never present example system readings as live data. |
| Motion | Optional short transitions only; respect `prefers-reduced-motion`. No autoplay, parallax, decorative cursor effects or required carousel. |

Use native light/dark preference via `prefers-color-scheme`; a manual switch is
optional and should not be required to read the site. Verify all actual
foreground/background pairs for WCAG 2.2 AA contrast, including focus,
hover, disabled and error states. Do not rely on colour alone.

## Information architecture

For the first release, prefer one focused landing page and links to the existing
documentation rather than duplicating a large documentation site.

1. **Header:** Preen mark and name; links to Features, How it works, FAQ and
   GitHub. Include a skip link and a usable keyboard/mobile menu if needed.
2. **Hero:** “A calmer way to maintain your Linux desktop.” Explain in one
   sentence that Preen is a GTK 3 utility for apps, cleanup, services and
   configuration backups. Primary CTA: **Run from source**; secondary CTA:
   **View on GitHub**. Show the dashboard screenshot with an example-data caption.
3. **Feature overview:** short, factual cards for app management, cleanup,
   system settings, services, backup and diagnostic logs. Show the Manage Apps
   screenshot as a second, non-interactive illustration.
4. **How it works:** install dependencies, start with Simulate, review logs and
   confirm a real action. Explain that Simulate is not a no-write sandbox and
   cleanup sizes are estimates. Link to the full safety guidance.
5. **Availability:** name Debian/Ubuntu-family intent and the external tools
   needed for individual features. Link to the actual release page; offer a
   binary download button only when that exact asset exists and is verified.
6. **Privacy and trust:** summarize local settings and the absence of built-in
   app telemetry, while noting package repositories and external tools can use
   the network. Link to the complete desktop privacy and security policies.
7. **FAQ:** answer what Preen does, distribution/tool requirements, root and
   polkit, Simulate limits, privacy, app-only appearance and the fact that the
   folder organizer is planned rather than available.
8. **Footer:** source, user guide, changelog, contribution guidance, license,
   third-party notices, security, desktop privacy and the future site's own
   privacy notice. Do not invent an organization address or contact address.

Suggested navigation: `/` for the landing page, with clear section anchors;
link directly to the repository's existing guide and policies initially. Add
separate `/download/`, `/privacy/` or `/docs/` pages only when their content
and a real domain have been approved. Each published page needs one canonical
URL and an owner for keeping it current.

## SEO, generative-engine and answer-engine readiness

- **Answer-first copy:** explain what Preen is, who it is for, what it does and
  its limits in ordinary, crawlable HTML. Use descriptive headings, concise FAQ
  answers, meaningful link text and screenshot alt text rather than keyword
  stuffing or text baked into images. Link claims to the source, guide and
  changelog so readers and answer engines can verify them.
- **Metadata:** use a distinct title and description for each page. Starting
  point for the landing page: title “Preen | Linux Apps, Cleanup and System
  Maintenance”; description “Manage Linux apps, review cleanup, inspect
  services and back up configuration with Preen's open-source GTK desktop app.”
  Add accurate Open Graph metadata and a real social-preview image with alt
  text. Set canonical URLs only after the production domain is chosen.
- **Technical discovery:** publish a valid sitemap and `robots.txt` for the
  actual host; make text and navigation available in initial HTML; use proper
  status codes, HTTPS and consistent canonical redirects. Do not index staging.
- **Structured data:** consider `SoftwareApplication` JSON-LD for visible,
  verifiable details such as name, Linux, description, license and source URL.
  Add a version or `downloadUrl` only when the matching public release and asset
  exist. FAQ markup, if used, must match visible answers; search enhancements
  are not guaranteed. Never invent offers, ratings, reviews or availability.
- **GEO/AEO:** make each FAQ answer self-contained and factual, with a link to
  the authoritative documentation; clearly distinguish implemented features
  from proposals. SEO, citations and structured data cannot guarantee search
  rankings, rich results or inclusion in AI answers.
- **Regional relevance:** describe supported distributions accurately and add
  translations only when reviewed by fluent contributors. Do not fabricate
  local business details or supported languages.

## Implementation and privacy choices

- Build a static, semantic HTML/CSS site; add a small amount of progressive
  JavaScript only if a real interaction needs it. A framework is optional, not a
  prerequisite. Core content and source-install links must work without JS.
- Store and serve approved, appropriately sized local assets; preserve the
  originals in this repository. No third-party fonts or embedded trackers by
  default. Review screenshots for personal data before any new publication.
- Host and domain are to be selected. Document the host's access logs, retention,
  processors, contact path and applicable rights in a **website-specific**
  privacy notice before launch. “No analytics” would not mean “no server logs.”
  If analytics, forms, cookies or third-party services are later added, evaluate
  consent and legal requirements and update that notice first.
- Use HTTPS and appropriate hosting security headers, including a reviewed
  Content Security Policy, `Referrer-Policy` and `X-Content-Type-Options`.
  Enable HSTS only after confirming HTTPS and domain configuration. Keep
  dependencies and deployment credentials out of the published site.
- Derive displayed release/version information from a verified source at build
  time or maintain it manually. Do not link to `.deb` or AppImage files merely
  because the build scripts can create them.

## Delivery stages

1. **Content and design:** approve copy, information architecture, screenshots,
   target audiences, light/dark components and domain/hosting. Confirm a private
   security contact and website privacy details with the project owner.
2. **Static implementation:** build responsive semantic pages, local assets,
   navigation and accurate links; use the no-gradient palette throughout.
3. **Search and accessibility:** add metadata, sitemap and verified structured
   data; manually test keyboard, focus order, screen readers, contrast, zoom,
   reduced motion and layouts from 320 px upward. Run automated accessibility and
   link checks as supplements, not substitutes.
4. **Prelaunch:** verify every download and claim against the published release;
   check privacy disclosures, security headers and the production canonical URL.
   Aim for Lighthouse accessibility and performance scores of at least 90 on
   representative mobile and desktop runs, recording actual results rather than
   treating scores as a guarantee.
5. **Launch and maintain:** deploy on the approved host, verify indexing and
   links, and review content whenever app behaviour, release assets, policy or
   third-party services change.

### Acceptance checklist

- [ ] No CSS, SVG or image treatment introduces a gradient.
- [ ] The site is usable without JS and with keyboard, zoom and reduced motion.
- [ ] Screenshots have alt text and captions; no fake metrics or unsupported claims.
- [ ] Installation links point to assets that actually exist, or to source.
- [ ] Desktop and website privacy notices accurately describe their own scope.
- [ ] Canonical URLs, sitemap, robots, metadata and any JSON-LD match the live site.
- [ ] Manual and automated accessibility, security, link and responsive checks
      are recorded, including what was not tested.
