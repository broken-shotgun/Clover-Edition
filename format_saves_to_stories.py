
from pathlib import Path
from storymanager import Story
from slugify import slugify

def save_to_file(context, story):
    save_file_name = slugify(context, max_length=240)
    save_file_path = f"saves/formatted/{save_file_name}.txt"

    if Path(save_file_path).exists():
        print(f"- {save_file_name}.txt exists, skipping...")
        return

    with open(save_file_path, "w", encoding="utf-8") as f:
        f.write(f"{context}\n\n{story.get_story()}")
    print(f"* Saved {save_file_name}.txt")

def save_to_csv(context, story):
    post_title = slugify(context, max_length=240)
    post_content = story.get_story().replace('"', '\\"').replace("'", "\\'")
    # "post_title","post_type","post_author","post_status","post_content"
    # "{post_title}","post","jason","draft"
    with open(f"saves/formatted/k9000_posts.csv", "a", encoding="utf-8") as f:
        f.write(f'"{post_title}","post","jason","draft","<pre class=\\"wp-block-preformatted alignwide\\">{post_content}</pre>"\n')

if __name__ == '__main__':
    p = Path('.')
    saves = [fp for fp in list(p.glob('saves/*.json')) if fp.is_file()]
    # with open(f"saves/formatted/k9000_posts.csv", "w", encoding="utf-8") as f:
    #    f.write('"post_title","post_type","post_author","post_status","post_content"\n')
    for save in saves:
        with save.open() as file:
            new_story = Story(None)
            new_story.from_json(file.read())
            save_to_file(new_story.context, new_story)
            # save_to_csv(new_story.context, new_story)
    print("Success!")

