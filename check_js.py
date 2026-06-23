# Print EVERY character on line 284 with its category
with open('C:/Users/29473/Desktop/AI_Resume_System/frontend/index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

line = lines[283]  # line 284, 0-indexed
print(f'Line length: {len(line)} chars')
print()

# Find all { and } positions
for i, ch in enumerate(line):
    if ch in '{}':
        context = line[max(0,i-10):i+5]
        print(f'  pos {i}: {repr(ch)} ctx: ...{repr(context)}...')
