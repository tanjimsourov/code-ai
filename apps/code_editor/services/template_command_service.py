from __future__ import annotations

import json
import re
from typing import Any

from ..exceptions import InvalidRequestException
from .chat_service import ChatService


_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "build",
    "create",
    "dashboard",
    "design",
    "for",
    "from",
    "generate",
    "in",
    "just",
    "layout",
    "make",
    "of",
    "on",
    "screen",
    "template",
    "web",
    "webpage",
    "website",
    "table",
    "the",
    "to",
    "with",
}


class TemplateCommandService:
    """Turn a natural-language command into a ready-to-place template payload."""

    TEMPLATE_CATALOG: list[dict[str, Any]] = [
        {
            "kind": "dashboard",
            "template_key": "WaterConservationDashboard",
            "title": "Water Conservation Dashboard",
            "preview_width": 1280,
            "preview_height": 720,
            "default_subtitle": "Smart water management and conservation",
            "default_summary": "A high-contrast water intelligence dashboard with KPI cards and usage insights.",
            "aliases": [
                "water",
                "conservation",
                "usage",
                "aqua",
                "leak",
                "flow",
                "hydro",
                "irrigation",
            ],
        },
        {
            "kind": "dashboard",
            "template_key": "RenewableEnergyAnalytics",
            "title": "Renewable Energy Analytics",
            "preview_width": 1280,
            "preview_height": 720,
            "default_subtitle": "Live renewable energy intelligence",
            "default_summary": "A clean energy monitoring dashboard focused on production, savings, and performance.",
            "aliases": [
                "renewable",
                "energy",
                "power",
                "grid",
                "analytics",
                "kwh",
                "electricity",
            ],
        },
        {
            "kind": "dashboard",
            "template_key": "SolarLiveDashboard",
            "title": "Solar Live Dashboard",
            "preview_width": 1280,
            "preview_height": 720,
            "default_subtitle": "Solar production in real time",
            "default_summary": "A solar-focused control-room template with live generation and efficiency visuals.",
            "aliases": [
                "solar",
                "panel",
                "pv",
                "sun",
                "inverter",
                "photovoltaic",
            ],
        },
        {
            "kind": "dashboard",
            "template_key": "AirQualityMonitor",
            "title": "Air Quality Monitor",
            "preview_width": 1280,
            "preview_height": 720,
            "default_subtitle": "AQI, particulate, and pollution trends",
            "default_summary": "A command-center style air quality screen for indoor or city monitoring.",
            "aliases": [
                "air",
                "quality",
                "aqi",
                "pollution",
                "pm2.5",
                "co2",
                "environment",
            ],
        },
        {
            "kind": "dashboard",
            "template_key": "SmartHomeDashboard",
            "title": "Smart Home Dashboard",
            "preview_width": 1280,
            "preview_height": 720,
            "default_subtitle": "Connected devices and automation insights",
            "default_summary": "A sleek smart-building dashboard with room, energy, and automation signals.",
            "aliases": [
                "smart",
                "home",
                "building",
                "iot",
                "occupancy",
                "automation",
                "room",
            ],
        },
        {
            "kind": "dashboard",
            "template_key": "SmartWasteManagement",
            "title": "Smart Waste Management",
            "preview_width": 1280,
            "preview_height": 720,
            "default_subtitle": "Collection routes and recycling intelligence",
            "default_summary": "A municipal operations layout for waste, recycling, and route KPIs.",
            "aliases": [
                "waste",
                "trash",
                "recycling",
                "bin",
                "garbage",
                "route",
                "collection",
            ],
        },
        {
            "kind": "dashboard",
            "template_key": "EVChargingStationsPage",
            "title": "EV Charging Stations",
            "preview_width": 1280,
            "preview_height": 720,
            "default_subtitle": "Charging activity and station availability",
            "default_summary": "A mobility dashboard for chargers, utilization, and electric vehicle traffic.",
            "aliases": [
                "ev",
                "charging",
                "charger",
                "vehicle",
                "station",
                "mobility",
                "battery",
            ],
        },
        {
            "kind": "dashboard",
            "template_key": "AgricultureMonitor",
            "title": "Agriculture Monitor",
            "preview_width": 1280,
            "preview_height": 720,
            "default_subtitle": "Crop, soil, and irrigation intelligence",
            "default_summary": "A precision agriculture template for farms, greenhouses, and irrigation data.",
            "aliases": [
                "agriculture",
                "farm",
                "crop",
                "soil",
                "greenhouse",
                "irrigation",
                "field",
            ],
        },
        {
            "kind": "webpage",
            "template_key": "LargeWebpageTemplate",
            "title": "Large Webpage Template",
            "preview_width": 1600,
            "preview_height": 900,
            "default_subtitle": "Large-format webpage style content canvas",
            "default_summary": "A wide webpage layout with hero, sections, and rich content blocks for enterprise storytelling.",
            "aliases": [
                "webpage",
                "website",
                "web",
                "portal",
                "landing",
                "page",
                "article",
                "story",
                "longform",
                "enterprise",
            ],
        },
        {
            "kind": "table",
            "template_key": "LargeDataTableTemplate",
            "title": "Large Data Table Template",
            "preview_width": 1600,
            "preview_height": 900,
            "default_subtitle": "Command center table and KPI matrix",
            "default_summary": "A high-density data-table template with KPI strips and multi-row operational records.",
            "aliases": [
                "table",
                "grid",
                "rows",
                "columns",
                "sheet",
                "spreadsheet",
                "matrix",
                "leaderboard",
                "comparison",
                "report",
                "dataset",
            ],
        },
    ]

    def __init__(self) -> None:
        self.chat_service = ChatService()

    def generate_template_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "").strip()
        if not command:
            raise InvalidRequestException("Command is required")

        canvas = payload.get("canvas") if isinstance(payload.get("canvas"), dict) else {}
        canvas_width = self._bounded_int(canvas.get("width"), 1920, 320, 7680)
        canvas_height = self._bounded_int(canvas.get("height"), 1080, 320, 7680)
        orientation = str(payload.get("orientation") or "").strip().lower()
        if orientation not in {"landscape", "portrait"}:
            orientation = "portrait" if canvas_height > canvas_width else "landscape"

        language = str(payload.get("language") or "en").strip().lower()
        if language not in {"en", "nl"}:
            language = "en"

        target_audience = str(payload.get("target_audience") or "").strip()
        brand_style = str(payload.get("brand_style") or "").strip()
        template_mode = str(payload.get("template_mode") or "auto").strip().lower()
        if template_mode not in {"auto", "dashboard", "webpage", "table"}:
            template_mode = "auto"

        catalog_item, confidence, matched_tags = self._select_catalog_item(
            command=command,
            template_mode=template_mode,
        )
        placement = self._build_placement(catalog_item, canvas_width, canvas_height)
        generated = self._build_fallback_content(
            catalog_item=catalog_item,
            command=command,
            language=language,
            target_audience=target_audience,
            brand_style=brand_style,
        )
        warnings: list[str] = []
        provider_used = "deterministic-fallback"

        try:
            ai_content = self._generate_ai_content(
                command=command,
                language=language,
                template_title=catalog_item["title"],
                matched_tags=matched_tags,
                target_audience=target_audience,
                brand_style=brand_style,
            )
            if ai_content:
                generated = self._merge_generated_content(generated, ai_content)
                provider_used = "code_editor_chat"
            else:
                warnings.append("AI returned no structured override. Used deterministic template copy.")
        except Exception as exc:
            warnings.append(f"AI copy enhancement unavailable. Used deterministic template copy. ({exc})")

        return {
            "template_key": catalog_item["template_key"],
            "template_title": catalog_item["title"],
            "summary": generated["summary"],
            "placement": placement,
            "props": generated["props"],
            "provider_used": provider_used,
            "warnings": warnings,
            "confidence": confidence,
            "matched_tags": matched_tags,
            "template_mode_used": template_mode,
        }

    def _select_catalog_item(self, command: str, template_mode: str) -> tuple[dict[str, Any], float, list[str]]:
        command_lc = command.lower()
        tokens = self._tokenize(command_lc)

        best_item = self.TEMPLATE_CATALOG[0]
        best_score = -1.0
        best_matches: list[str] = []

        for item in self.TEMPLATE_CATALOG:
            score = 0.0
            matches: list[str] = []
            for alias in item["aliases"]:
                alias_lc = alias.lower()
                if " " in alias_lc:
                    if alias_lc in command_lc:
                        score += 2.6
                        matches.append(alias)
                elif alias_lc in tokens:
                    score += 1.35
                    matches.append(alias)
                elif alias_lc in command_lc:
                    score += 0.55
                    matches.append(alias)

            if "dashboard" in command_lc:
                score += 0.25
            if "table" in command_lc or "grid" in command_lc:
                score += 0.35 if item.get("kind") == "table" else 0
            if "webpage" in command_lc or "website" in command_lc or "portal" in command_lc:
                score += 0.35 if item.get("kind") == "webpage" else 0

            if template_mode != "auto":
                if item.get("kind") == template_mode:
                    score += 2.4
                else:
                    score -= 0.3

            if item["template_key"] == "WaterConservationDashboard" and score <= 0:
                score += 0.2

            if score > best_score:
                best_item = item
                best_score = score
                best_matches = matches

        confidence = round(max(0.42, min(0.98, 0.42 + max(best_score, 0) * 0.11)), 2)
        return best_item, confidence, sorted(set(best_matches))

    def _build_placement(self, catalog_item: dict[str, Any], canvas_width: int, canvas_height: int) -> dict[str, int]:
        preview_width = int(catalog_item.get("preview_width") or 1280)
        preview_height = int(catalog_item.get("preview_height") or 720)
        outer_padding_x = max(24, round(canvas_width * 0.06))
        outer_padding_y = max(24, round(canvas_height * 0.06))
        available_width = max(320, canvas_width - outer_padding_x * 2)
        available_height = max(240, canvas_height - outer_padding_y * 2)

        scale = min(available_width / preview_width, available_height / preview_height)
        scale = max(0.25, min(scale, 1.75))

        width = max(320, int(round(preview_width * scale)))
        height = max(200, int(round(preview_height * scale)))
        x = max(0, int(round((canvas_width - width) / 2)))
        y = max(0, int(round((canvas_height - height) / 2)))

        return {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        }

    def _build_fallback_content(
        self,
        *,
        catalog_item: dict[str, Any],
        command: str,
        language: str,
        target_audience: str,
        brand_style: str,
    ) -> dict[str, Any]:
        language_key = "nl" if language == "nl" else "en"
        compact_subject = self._derive_subject(command, fallback=catalog_item["title"])
        title = compact_subject or catalog_item["title"]
        subtitle = catalog_item["default_subtitle"]
        summary_parts = [catalog_item["default_summary"]]
        if target_audience:
            summary_parts.append(f"Tailored for {target_audience}.")
        if brand_style:
            summary_parts.append(f"Visual tone: {brand_style}.")
        summary = " ".join(summary_parts).strip()

        texts_payload: dict[str, Any] = {
            language_key: {
                "title": title,
                "subtitle": subtitle,
            }
        }

        if catalog_item["template_key"] == "WaterConservationDashboard":
            texts_payload[language_key] = {
                "title": title,
                "subtitle": subtitle,
                "dailyUsage": "Daily Usage" if language_key == "en" else "Dagelijks Verbruik",
                "dailyValue": "142 L",
                "savingsGoal": "45% Target Achieved" if language_key == "en" else "45% Doel Bereikt",
                "info": {
                    "description": summary,
                    "liveChip": "• Live Tracking" if language_key == "en" else "• Live Tracking",
                    "aiChip": "• AI Insights" if language_key == "en" else "• AI Inzichten",
                },
                "kpis": {
                    "shower": "Shower" if language_key == "en" else "Douche",
                    "showerValue": "68 L",
                    "kitchen": "Kitchen" if language_key == "en" else "Keuken",
                    "kitchenValue": "28 L",
                    "garden": "Garden" if language_key == "en" else "Tuin",
                    "gardenValue": "46 L",
                },
                "centerCard": {
                    "title": "Conservation Progress" if language_key == "en" else "Besparings Voortgang",
                    "note": "Towards sustainable water usage"
                    if language_key == "en"
                    else "Richting duurzaam watergebruik",
                },
            }
        elif catalog_item["template_key"] == "LargeWebpageTemplate":
            texts_payload[language_key] = {
                "title": title,
                "subtitle": subtitle,
                "hero": {
                    "headline": title,
                    "tagline": summary,
                    "primaryCta": "Launch Plan" if language_key == "en" else "Start Plan",
                    "secondaryCta": "View Metrics" if language_key == "en" else "Bekijk Metrics",
                },
                "highlights": [
                    {"label": "Live Modules" if language_key == "en" else "Live Modules", "value": "12"},
                    {"label": "Active Users" if language_key == "en" else "Actieve Gebruikers", "value": "4.8K"},
                    {"label": "Conversion" if language_key == "en" else "Conversie", "value": "37%"},
                ],
                "sections": [
                    {
                        "title": "Executive Overview" if language_key == "en" else "Overzicht",
                        "description": summary,
                        "bullets": [
                            "Large-format hero section for storytelling",
                            "Multi-column content blocks for detail",
                            "Action panel for conversion-driven campaigns",
                        ],
                    },
                    {
                        "title": "Operational Signals" if language_key == "en" else "Operationele Signalen",
                        "description": "Track modules, campaign performance, and delivery confidence.",
                        "bullets": [
                            "Top channels and audience segments",
                            "Automated anomaly watchlist",
                            "Regional rollout status and ownership",
                        ],
                    },
                ],
            }
        elif catalog_item["template_key"] == "LargeDataTableTemplate":
            texts_payload[language_key] = {
                "title": title,
                "subtitle": subtitle,
                "kpis": [
                    {"label": "Total Records" if language_key == "en" else "Totaal Records", "value": "12,840"},
                    {"label": "SLA Healthy" if language_key == "en" else "SLA Gezond", "value": "97.4%"},
                    {"label": "Incidents" if language_key == "en" else "Incidenten", "value": "14"},
                    {"label": "At Risk" if language_key == "en" else "Risico", "value": "62"},
                ],
                "table": {
                    "columns": [
                        "Region",
                        "Owner",
                        "Status",
                        "Latency",
                        "Uptime",
                        "Revenue",
                        "Updated",
                    ],
                    "rows": [
                        ["North", "Ops-A", "Healthy", "42 ms", "99.93%", "$142K", "2m ago"],
                        ["South", "Ops-B", "Warning", "89 ms", "98.87%", "$94K", "4m ago"],
                        ["West", "Ops-C", "Healthy", "37 ms", "99.97%", "$121K", "1m ago"],
                        ["East", "Ops-D", "Risk", "131 ms", "97.62%", "$78K", "6m ago"],
                        ["Global", "Ops-X", "Healthy", "58 ms", "99.21%", "$435K", "now"],
                    ],
                    "footerNote": summary,
                },
                "filterCard": {
                    "title": "Software Tender Filters" if language_key == "en" else "Software Tender Filters",
                    "searchPlaceholder": "Search software tender" if language_key == "en" else "Zoek software tender",
                    "dropdowns": [
                        {"label": "All Software Categories" if language_key == "en" else "Alle categorieën", "value": ""},
                        {"label": "All Urgency Levels" if language_key == "en" else "Alle urgentieniveaus", "value": ""},
                        {"label": "All Deadlines" if language_key == "en" else "Alle deadlines", "value": ""},
                        {"label": "All Values" if language_key == "en" else "Alle waarden", "value": ""},
                    ],
                    "quickFilters": ["Web Dev", "Mobile", "Critical", "Urgent"],
                    "helpText": "Bypass data only" if language_key == "en" else "Alleen bypass-gegevens",
                    "toggleLabel": "Bypass Data Only" if language_key == "en" else "Alleen bypass-gegevens",
                },
                "alert": {
                    "icon": "⚠️",
                    "title": "Error Loading Software Tenders" if language_key == "en" else "Fout bij laden",
                    "message": "Unexpected token '<'... is not valid JSON" if language_key == "en" else "Ongeldig JSON",
                    "buttonLabel": "Retry" if language_key == "en" else "Opnieuw proberen",
                    "accent": "orange",
                },
            }

        props = {
            "lang": language_key,
            "apiConfig": {
                "enabled": False,
                "endpoint": "",
            },
            "texts": texts_payload,
        }

        return {
            "summary": summary,
            "props": props,
        }

    def _generate_ai_content(
        self,
        *,
        command: str,
        language: str,
        template_title: str,
        matched_tags: list[str],
        target_audience: str,
        brand_style: str,
    ) -> dict[str, Any]:
        system_prompt = (
            "You generate structured copy for signage dashboards, webpage sections, and data tables. "
            "Return valid JSON only. No markdown, no code fences, no commentary. "
            'Schema: {"title": string, "subtitle": string, "summary": string, "description": string, '
            '"metric_value": string, "goal_label": string, "highlights": [string], '
            '"table_columns": [string], "table_rows": [[string]]}. '
            "Keep text concise and readable for large-format screens."
        )
        user_prompt = "\n".join(
            [
                f"Command: {command}",
                f"Language: {language}",
                f"Template: {template_title}",
                f"Matched tags: {', '.join(matched_tags) if matched_tags else 'none'}",
                f"Audience: {target_audience or 'general viewers'}",
                f"Brand style: {brand_style or 'modern analytics'}",
            ]
        )

        response = self.chat_service.chat_completion(
            messages=[{"role": "user", "content": user_prompt}],
            system_prompt=system_prompt,
            temperature=0.35,
            max_tokens=420,
            stream=False,
        )
        content = self._extract_assistant_content(response)
        if not content:
            return {}
        return self._parse_json_object(content)

    def _merge_generated_content(self, fallback: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
        merged = json.loads(json.dumps(fallback))
        summary = str(generated.get("summary") or "").strip()
        title = str(generated.get("title") or "").strip()
        subtitle = str(generated.get("subtitle") or "").strip()
        description = str(generated.get("description") or "").strip()
        metric_value = str(generated.get("metric_value") or "").strip()
        goal_label = str(generated.get("goal_label") or "").strip()
        highlights = generated.get("highlights") if isinstance(generated.get("highlights"), list) else []
        clean_highlights = [str(item).strip() for item in highlights if str(item).strip()]
        table_columns = generated.get("table_columns") if isinstance(generated.get("table_columns"), list) else []
        clean_table_columns = [str(item).strip() for item in table_columns if str(item).strip()]
        table_rows = generated.get("table_rows") if isinstance(generated.get("table_rows"), list) else []
        clean_table_rows: list[list[str]] = []
        for row in table_rows:
            if not isinstance(row, list):
                continue
            clean_row = [str(cell).strip() for cell in row if str(cell).strip()]
            if clean_row:
                clean_table_rows.append(clean_row)

        if summary:
            merged["summary"] = summary

        texts = merged["props"].get("texts") if isinstance(merged["props"].get("texts"), dict) else {}
        lang_key = next(iter(texts.keys()), "en")
        lang_payload = texts.get(lang_key) if isinstance(texts.get(lang_key), dict) else {}
        template_key = self._detect_template_key_from_payload(lang_payload)

        if title:
            lang_payload["title"] = title
        if subtitle:
            lang_payload["subtitle"] = subtitle
        if description:
            info = lang_payload.get("info") if isinstance(lang_payload.get("info"), dict) else {}
            info["description"] = description
            lang_payload["info"] = info

        if template_key == "WaterConservationDashboard":
            if metric_value:
                lang_payload["dailyValue"] = metric_value
            if goal_label:
                lang_payload["savingsGoal"] = goal_label
            if clean_highlights:
                kpis = lang_payload.get("kpis") if isinstance(lang_payload.get("kpis"), dict) else {}
                if len(clean_highlights) > 0:
                    kpis["showerValue"] = clean_highlights[0]
                if len(clean_highlights) > 1:
                    kpis["kitchenValue"] = clean_highlights[1]
                if len(clean_highlights) > 2:
                    kpis["gardenValue"] = clean_highlights[2]
                if kpis:
                    lang_payload["kpis"] = kpis
        elif template_key == "LargeWebpageTemplate":
            hero = lang_payload.get("hero") if isinstance(lang_payload.get("hero"), dict) else {}
            if title:
                hero["headline"] = title
            if description:
                hero["tagline"] = description
            if hero:
                lang_payload["hero"] = hero

            if clean_highlights:
                existing_highlights = (
                    lang_payload.get("highlights") if isinstance(lang_payload.get("highlights"), list) else []
                )
                hydrated_highlights = []
                for idx, highlight in enumerate(clean_highlights[:3]):
                    label = f"Signal {idx + 1}"
                    value = highlight
                    if idx < len(existing_highlights) and isinstance(existing_highlights[idx], dict):
                        label = str(existing_highlights[idx].get("label") or label)
                    hydrated_highlights.append({"label": label, "value": value})
                if hydrated_highlights:
                    lang_payload["highlights"] = hydrated_highlights
            if isinstance(generated.get("filterCard"), dict):
                existing_filters = (
                    lang_payload.get("filterCard") if isinstance(lang_payload.get("filterCard"), dict) else {}
                )
                merged_filters = {**existing_filters, **generated.get("filterCard", {})}
                lang_payload["filterCard"] = merged_filters
            if isinstance(generated.get("alert"), dict):
                existing_alert = lang_payload.get("alert") if isinstance(lang_payload.get("alert"), dict) else {}
                merged_alert = {**existing_alert, **generated.get("alert", {})}
                lang_payload["alert"] = merged_alert
        elif template_key == "LargeDataTableTemplate":
            table = lang_payload.get("table") if isinstance(lang_payload.get("table"), dict) else {}
            if clean_table_columns:
                table["columns"] = clean_table_columns[:10]
            if clean_table_rows:
                table["rows"] = clean_table_rows[:20]
            if description:
                table["footerNote"] = description
            if table:
                lang_payload["table"] = table

            kpis = lang_payload.get("kpis") if isinstance(lang_payload.get("kpis"), list) else []
            if metric_value or goal_label:
                next_kpis = []
                if metric_value:
                    next_kpis.append({"label": "Primary Metric", "value": metric_value})
                if goal_label:
                    next_kpis.append({"label": "Target", "value": goal_label})
                if clean_highlights:
                    next_kpis.extend(
                        {"label": f"Signal {idx + 1}", "value": value}
                        for idx, value in enumerate(clean_highlights[:2])
                    )
                if next_kpis:
                    kpis = next_kpis
            if kpis:
                lang_payload["kpis"] = kpis

        texts[lang_key] = lang_payload
        merged["props"]["texts"] = texts
        return merged

    def _detect_template_key_from_payload(self, lang_payload: dict[str, Any]) -> str:
        if "kpis" in lang_payload and "info" in lang_payload:
            return "WaterConservationDashboard"
        if "table" in lang_payload:
            return "LargeDataTableTemplate"
        if "hero" in lang_payload or "sections" in lang_payload:
            return "LargeWebpageTemplate"
        return "generic"

    def _extract_assistant_content(self, response: dict[str, Any]) -> str:
        if not isinstance(response, dict):
            return ""

        content = response.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

        choices = response.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    text = message["content"].strip()
                    if text:
                        return text
                delta = choice.get("delta")
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    text = delta["content"].strip()
                    if text:
                        return text
        return ""

    def _parse_json_object(self, content: str) -> dict[str, Any]:
        clean = content.strip()
        if not clean:
            return {}

        fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.IGNORECASE | re.DOTALL).strip()
        candidates = [fenced]

        start = fenced.find("{")
        end = fenced.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(fenced[start : end + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        return {}

    def _derive_subject(self, command: str, fallback: str) -> str:
        tokens = [token for token in self._tokenize(command) if token not in _STOPWORDS]
        if not tokens:
            return fallback

        subject = " ".join(tokens[:4]).strip()
        if not subject:
            return fallback
        return " ".join(word.capitalize() for word in subject.split())

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _bounded_int(self, value: Any, fallback: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(round(float(value)))
        except (TypeError, ValueError):
            parsed = fallback
        return max(minimum, min(maximum, parsed))
