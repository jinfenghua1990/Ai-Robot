import requests
import json

r = requests.get('http://127.0.0.1:9000/api/rotation', params={'date': '2026-06-22', 'days': '5'})
d = r.json()

print('=== Rotation API Test ===')
print(f'Status: {r.status_code}')
print()

print('Signals:')
for s in d.get('signals', []):
    print(f'  {s}')

print()
streaks = d.get('streaks', {})
top = sorted(streaks.items(), key=lambda x: x[1], reverse=True)[:10]
print('Top streaks:')
for sector, days in top:
    if days > 0:
        print(f'  {sector}: {days} days')

print()
print(f'Total sectors with streaks: {len(streaks)}')
print(f'Sectors with streak >= 2: {sum(1 for v in streaks.values() if v >= 2)}')
print(f'Sectors with streak >= 3: {sum(1 for v in streaks.values() if v >= 3)}')
