import json

#from pathlib import Path
#from storymanager import Story
#from slugify import slugify


# def save_to_file(context, story):
#     save_file_name = slugify(context, max_length=240)
#     save_file_path = f"saves/formatted/{save_file_name}.txt"

#     if Path(save_file_path).exists():
#         print(f"- {save_file_name}.txt exists, skipping...")
#         return

#     with open(save_file_path, "w", encoding="utf-8") as f:
#         f.write(f"{context}\n\n{story.get_story()}")
#     print(f"* Saved {save_file_name}.txt")

# def save_to_csv(context, story):
#     post_title = slugify(context, max_length=240)
#     post_content = story.get_story().replace('"', '\\"').replace("'", "\\'")
#     # "post_title","post_type","post_author","post_status","post_content"
#     # "{post_title}","post","jason","draft"
#     with open(f"saves/formatted/k9000_posts.csv", "a", encoding="utf-8") as f:
#         f.write(f'"{post_title}","post","jason","draft","<pre class=\\"wp-block-preformatted alignwide\\">{post_content}</pre>"\n')

def convert_to_xml(aid_story_json):
    story_xml = "<Story>"

    story_xml += f"<Title>{aid_story_json['title']}</Title>"
    story_xml += f"<Date>{aid_story_json['updatedAt']}</Date>"

    actions = aid_story_json["actions"]
    story_xml += "<Actions>"
    for action in actions:
        story_xml += action["text"]
    story_xml += "</Actions>"

    story_xml += "</Story>"
    return story_xml


if __name__ == '__main__':
    with open(f"saves/formatted/aidungeon_posts.xml", "w", encoding="utf-8") as xml_file:
        with open(f"saves/aidungeon_official/stories.json", "r", encoding="utf-8") as stories_file:
            stories_dict = json.loads(stories_file.read())
            stories = stories_dict["stories"]

            xml_file.write("<root>")
            
            for story in stories:
                xml_file.write(convert_to_xml(story))
                print('.')
            print('\nDone!\n')
            
            xml_file.write("</root>")
    print("Success!")


# if __name__ == '__main__':
#     p = Path('.')
#     saves = [fp for fp in list(p.glob('saves/*.json')) if fp.is_file()]
#     # with open(f"saves/formatted/k9000_posts.csv", "w", encoding="utf-8") as f:
#     #    f.write('"post_title","post_type","post_author","post_status","post_content"\n')
#     for save in saves:
#         with save.open() as file:
#             new_story = Story(None)
#             new_story.from_json(file.read())
#             # save_to_file(new_story.context, new_story)
#             # save_to_csv(new_story.context, new_story)
#     print("Success!")

