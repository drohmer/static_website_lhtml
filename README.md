# Static website template with Jinja

Generate a website in directory _site/ from template sources in src/
* src/templates/: templates files
* src/layout/: all layouts, css, etc.

Generating the website
```
python generate.py
```

Special files:
- no_web_parse.txt: Do not parse any files not subdirs
- no_web_parse_subdirs: Do not parse subdirs, but still parse files
- private/: do not parse directory
- private_web_temp/: parse but remove at the end