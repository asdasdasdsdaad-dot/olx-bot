#!/usr/bin/env python3
"""
OLX Watcher Bot — следит за объявлениями по ключевым словам и шлёт
подозрительно дешёвые (относительно рынка) лоты в Telegram.
"""

import json
import os
import time
import re
import statistics
import requests
from bs4 import BeautifulSoup

# ========================= НАСТРОЙКИ =========================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

WATCHES = [
    {
        "name": "Наушники",
        "url": "https://www.olx.ua/uk/list/q-navushniki/",
        "min_price": 50,
        "discount_ratio": 0.6,    # алертим, если цена <= 60% от медианной цены по категории
    },
    {
        "name": "Повербанки",
        "url": "https://www.olx.ua/uk/list/q-powerbank/",
        "min_price": 50,
        "discount_ratio": 0.6,
    },
]

SEEN_FILE = "seen_listings.json"

# ========================= TELEGRAM =========================


def send_telegram_message(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}

    for attempt in range(3):
        try:
            r = requests.post(url, data=payload, timeout=15)
        except requests.RequestException as e:
            print(f"[telegram] не удалось отправить сообщение: {e}")
            return

        if r.ok:
            return

        if r.status_code == 429:
            retry_after = 5
            try:
                retry_after = r.json().get("parameters", {}).get("retry_after", 5)
            except ValueError:
                pass
            print(f"[telegram] лимит запросов, жду {retry_after} сек и пробую снова...")
            time.sleep(retry_after + 1)
            continue

        print(f"[telegram] ошибка отправки: {r.status_code} {r.text}")
        return

    print("[telegram] не удалось отправить сообщение после нескольких попыток")


# ========================= ХРАНИЛИЩЕ "УЖЕ ВИДЕЛИ" =========================


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set) -> None:
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)


# ========================= ПАРСИНГ OLX =========================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en;q=0.7",
}


def parse_price(text: str):
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return float(digits) if digits else None


def parse_listings(html: str):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    cards = soup.select('div[data-cy="l-card"]') or soup.select("div.css-1sw7q4x") or soup.select("div[data-testid='listing-grid'] > div")

    for card in cards:
        title_el = card.select_one("h4, h6, [data-cy='ad-card-title'] h4")
        price_el = card.select_one("[data-testid='ad-price'], p[data-testid='ad-price']")
        link_el = card.select_one("a")

        if not (title_el and price_el and link_el):
            continue

        title = title_el.get_text(strip=True)
        price = parse_price(price_el.get_text(strip=True))
        href = link_el.get("href", "")
        if href and href.startswith("/"):
            href = "https://www.olx.ua" + href

        if price is None:
            continue

        results.append({"title": title, "price": price, "link": href})

    return results


def fetch_listings(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[fetch] ошибка запроса к {url}: {e}")
        return []
    return parse_listings(r.text)


# ========================= ОСНОВНОЙ ЦИКЛ =========================


def make_listing_id(watch_name: str, link: str) -> str:
    return f"{watch_name}::{link}"


def run_once(seen: set) -> set:
    for watch in WATCHES:
        listings = fetch_listings(watch["url"])
        print(f"[{watch['name']}] найдено карточек: {len(listings)}")

        valid_prices = [
            item["price"] for item in listings
            if item["price"] >= watch["min_price"]
        ]

        if len(valid_prices) < 5:
            print(f"[{watch['name']}] слишком мало объявлений для анализа цены, пропускаю")
            continue

        median_price = statistics.median(valid_prices)
        threshold = median_price * watch["discount_ratio"]
        print(f"[{watch['name']}] медианная цена: {median_price:.0f} грн, порог алерта: {threshold:.0f} грн")

        for item in listings:
            lid = make_listing_id(watch["name"], item["link"])
            if lid in seen:
                continue
            seen.add(lid)

            price = item["price"]
            if watch["min_price"] <= price <= threshold:
                discount_pct = round((1 - price / median_price) * 100)
                text = (
                    f"🔥 <b>{watch['name']}</b> — дешевле рынка на {discount_pct}%\n"
                    f"{item['title']}\n"
                    f"Цена: {int(price)} грн (медиана по категории: {median_price:.0f} грн)\n"
                    f"{item['link']}"
                )
                send_telegram_message(text)
                print(f"[alert] отправлено: {item['title']} — {price} грн (-{discount_pct}%)")
                time.sleep(1.5)

    return seen


def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("Не заданы BOT_TOKEN и/или CHAT_ID. Задай их как переменные окружения (GitHub Secrets).")
        return

    seen = load_seen()
    print("Проверяю объявления...")
    seen = run_once(seen)
    save_seen(seen)
    print("Готово.")


if __name__ == "__main__":
    main()
