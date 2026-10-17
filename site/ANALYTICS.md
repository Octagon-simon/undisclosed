# Analytics

The landing page uses Google Analytics 4 with a single measurement ID. Nothing
is requested from Google, and no cookie is set, until the visitor presses
**Allow analytics**.

## Set the measurement ID

One line in `site/index.html`:

```js
window.UNDISCLOSED_ANALYTICS = {
  ga4: "G-XXXXXXXXXX",
  site: "undisclosed",
  debug: /[?&]ga_debug=1\b/.test(location.search)
};
```

An empty or malformed ID disables the whole block, including the consent bar.
The regex is `^G-[A-Z0-9]{6,}$`, so an ads tag (`AW-`) or a Tag Manager
container (`GTM-`) will not load. Use the GA4 data stream ID.

## Consent

- Choice is stored in `localStorage` under `undisclosed-consent` as `granted`
  or `denied`.
- First visit: the bar appears after 700 ms, bottom left, clear of the
  "Built with Undisclosed" badge on mobile.
- Footer link **Analytics settings** reopens it. Turning analytics off stops
  all future collection on this browser. It does not delete hits already sent.
- The bar is shown to every first-time visitor, including browsers sending
  `Do Not Track` or `Global Privacy Control`. The visitor decides; nothing is
  measured unless they press **Allow analytics**, and either choice is
  remembered.
- GA4 is configured with `anonymize_ip`, `allow_google_signals: false` and
  `allow_ad_personalization_signals: false`. Only `analytics_storage` is
  granted; ads storage stays denied.

## Events

All events carry `site: "undisclosed"`, and `debug_mode: true` when the page
was opened with `?ga_debug=1`.

| Event | Fires when | Params |
| --- | --- | --- |
| `page_view` | once per load, after consent | `page_location`, `page_path`, `page_title`, `site` |
| `consent_update` | visitor presses Allow | `choice` |
| `cta_click` | a tagged call to action is clicked | `cta`, `cta_label`, `location`, `destination`, `outbound` |
| `nav_click` | a header or footer section link is clicked | `label`, `target`, `location` |
| `outbound_click` | an untagged link leaves the site | `domain`, `url`, `label`, `location` |
| `demo_play` | first play of the 35 s demo | `position` |
| `demo_progress` | 25 / 50 / 75 percent watched, once each | `percent` |
| `demo_complete` | the demo reaches the end | `duration` |
| `faq_open` | a straight-answer row is opened | `question`, `index` |
| `section_view` | a section is 20 percent in view, once | `section` |
| `scroll_depth` | 25 / 50 / 75 / 100 percent of the page, once each | `percent` |
| `theme_change` | light/dark toggle is used | `theme` |

`location` is the id of the enclosing section (`top`, `demo`, `panel`,
`capabilities`, `skills`, `privacy`, `open-source`, `download`), or `nav` /
`footer`.

### Tagged CTAs

These `data-ga-cta` values are on the page:

- `download_nav`, `download_hero`, `download_cta`
- `github_nav`, `github_hero`, `github_cta`
- `issues_open`, `issue_report`, `releases`, `source`
- `badge` (the floating "Built with Undisclosed" credit)

To tag another element, add `data-ga-cta="name"` to the link or button. To
override the label used in `cta_label`, add `data-ga-label`.

## Debugging

Open `https://octagon-simon.github.io/undisclosed/?ga_debug=1`, allow
analytics, then watch:

- GA4 Admin > DebugView (the `debug_mode` flag routes hits there)
- `window.dataLayer` in the console
- the Network tab, filtered to `googletagmanager.com`

A quick check that consent gating works: load the page in a fresh profile and
confirm zero requests to `googletagmanager.com` before pressing Allow.

## Suggested GA4 setup

1. Mark `cta_click` with `cta = download_hero` or `download_cta` as a key event.
2. Build one exploration: `section_view` by `section`, to see which part of the
   page people actually read.
3. Build a funnel from `demo_play` to `demo_complete` to `cta_click`.
4. Ignore `page_view` counts from the first week if the site is shared in a
   chat that prefetches links; GA4 counts them like real visits.
