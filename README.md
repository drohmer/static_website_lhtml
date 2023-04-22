# Static website template with Jinja

Generate a website in directory _site/ from template sources written in html/jinja2/lhtml

Generating the website
```
python generate.py -i configure_default.yaml
```

or 
```
cp configure_default.yaml configure.yaml
python generate.py
```



## Clone

```
git clone --recurse-submodules https://github.com/drohmer/static_website_lhtml.git
```

or
```
git clone https://github.com/drohmer/static_website_lhtml.git
cd static_website_lhtml/
git submodule init
git submodule update
```
