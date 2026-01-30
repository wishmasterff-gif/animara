---
name: browser
description: Автоматизация браузера через Playwright
version: 1.0.0
metadata:
  animara:
    requires:
      bins: ["playwright"]
    security:
      level: elevated
---

# 🌐 Browser

Автоматизация браузера через Playwright.

## Использование
```
browser(action="screenshot", url="https://example.com")
browser(action="click", selector="#button")
```
