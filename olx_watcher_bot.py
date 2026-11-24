#!/usr/bin/env python3
"""
OLX Watcher Bot — следит за объявлениями по ключевым словам и шлёт
подозрительно дешёвые лоты в Telegram.
"""

import json
import os
import time
import re
import requests
from bs4 import BeautifulSoup

# ========================= НАСТРОЙКИ =========================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

WATCHES = [
    {
        "name": "Наушники",
        "url": "https://www.olx.ua/uk/list/q-navushniki/",
        "max_price": 500,
        "min_price": 50,
    },
    {
        "name": "Повербанки",
        "url": "https://www.olx.ua/uk/list/q-powerbank/",
        "max_price": 400,
        "min_price": 50,
    },
]

CHECK_INTERVAL_SECONDS = 300
SEEN_FILE = "seen_listings.json"

# ========================= TELEGRAM =========================


def send_telegram_message(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}
    try:
        r = requests.post(url, data=payload, timeout=15)
        if not r.ok:
            print(f"[telegram] ошибка отправки: {r.status_code} {r.text}")
    except requests.RequestException as e:
        print(f"[telegram] не удалось отправить сообщение: {e}")


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

        for item in listings:
            lid = make_listing_id(watch["name"], item["link"])
            if lid in seen:
                continue
            seen.add(lid)

            price = item["price"]
            if watch["min_price"] <= price <= watch["max_price"]:
                text = (
                    f"🔥 <b>{watch['name']}</b>\n"
                    f"{item['title']}\n"
                    f"Цена: {int(price)} грн\n"
                    f"{item['link']}"
                )
                send_telegram_message(text)
                print(f"[alert] отправлено: {item['title']} — {price} грн")

    return seen


def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("Не заданы BOT_TOKEN и/или CHAT_ID. Задай их как переменные окружения.")
        return

    seen = load_seen()
    print("Бот запущен. Проверяю объявления...")

    while True:
        seen = run_once(seen)
        save_seen(seen)
        print(f"Жду {CHECK_INTERVAL_SECONDS} секунд до следующей проверки...\n")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
