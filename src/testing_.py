url_thing = "https://docs.google.com/document/d/e/2PACX-1vSvM5gDlNvt7npYHhp_XfsJvuntUhq184By5xO_pA4b_gCWeXb6dM6ZxwN8rE6S4ghUsCj2VKR21oEP/pub"

import requests
from bs4 import BeautifulSoup

def secret_message(url_entry):
  resp = requests.get(url_entry)
  soup = BeautifulSoup(resp.text, "html.parser")
  points_stored = []
  rows = soup.find_all("tr")
  # we need to go through them all

  for row in rows:
    cells = row.find_all(["td", "th"])
    cell_list = []
    for cell in cells:
      cell_text = cell.get_text(strip=True)
      cell_list.append(cell_text)
    try:

        x = int(cell_list[0])
        character_in_cell = cell_list[1]
        y = int(cell_list[2])
        points_stored.append((x, y, character_in_cell))
    except ValueError:
      continue

  if len(points_stored) < 1:
    return
  bounds_x = max(point[0] for point in points_stored)
  bounds_y = max(point[1] for point in points_stored)
  
  grid = []
  for y in range(bounds_y + 1):
    new_row = []
    for x in range(bounds_x + 1):
      new_row.append(" ")

    grid.append(new_row)


  for x, y, character in points_stored:
    grid[y][x] = character

  for y in range(bounds_y, -1, -1):
    print("".join(grid[y]))
    
  
  
    
      

# download the doc
# find the tabbles rows
# read the x and y per row and the character
# store the coordinates somewhere, most likely a double list
# create a grid myself
# place chracter in position
# print, does order matter?


print(secret_message(url_thing))