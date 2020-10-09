
from pathlib import Path
from storymanager import Story
from slugify import slugify

def save_to_file(context, story):
    save_file_name = slugify(context, max_length=240)

    with open(f"saves/formatted/{save_file_name}.txt", "w", encoding="utf-8") as f:
        f.write(f"{context}\n\n{story.get_story()}")
    print(f"Saved {save_file_name}.txt")

if __name__ == '__main__':
    p = Path('.')
    saves = [fp for fp in list(p.glob('saves/*.json')) if fp.is_file()]
    for save in saves:
        with save.open() as file:
            new_story = Story(None)
            new_story.from_json(file.read())
            save_to_file(new_story.context, new_story)
    print("Stories formatted!")

