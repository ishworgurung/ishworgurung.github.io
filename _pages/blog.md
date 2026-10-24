---
layout: default
permalink: /blog/
title: blog
nav: true
nav_order: 1
pagination:
  enabled: true
  collection: posts
  permalink: /page/:num/
  per_page: 5
  sort_field: date
  sort_reverse: true
  trail:
    before: 2
    after: 2
---

<div class="post notes-page">
  <header class="notes-header">
    <h1>{{ site.blog_name }}</h1>
    <p class="notes-tagline">{{ site.blog_description }}</p>
    <div class="notes-ornament" aria-hidden="true">⁂</div>
  </header>

  {% assign prev_year = "" %}
  <ul class="notes">
    {% for post in paginator.posts %}
      {% assign year = post.date | date: "%Y" %}
      {% if year != prev_year %}
        <li class="notes-year"><span>{{ year }}</span></li>
        {% assign prev_year = year %}
      {% endif %}
      {% comment %} Excerpt from the first real paragraph, not the opening heading. {% endcomment %}
      {% assign paras = post.content | split: "<p>" %}
      {% assign excerpt = "" %}
      {% for para in paras offset: 1 %}
        {% assign candidate = para | split: "</p>" | first | strip_html | strip %}
        {% if candidate.size > 60 %}
          {% assign excerpt = candidate | truncatewords: 38 %}
          {% break %}
        {% endif %}
      {% endfor %}
      {% assign words = post.content | strip_html | number_of_words %}
      {% assign minutes = words | divided_by: site.words_per_minute | plus: 1 %}
      <li class="note">
        <time class="note-date" datetime="{{ post.date | date_to_xmlschema }}">
          <span class="note-day">{{ post.date | date: "%d" }}</span>
          <span class="note-month">{{ post.date | date: "%b" }}</span>
        </time>
        <div class="note-body">
          <h3 class="note-title"><a href="{{ post.url | relative_url }}">{{ post.title }}</a></h3>
          {% if excerpt != "" %}<p class="note-excerpt">{{ excerpt }}</p>{% endif %}
          <p class="note-meta">{{ minutes }} min read</p>
        </div>
      </li>
    {% endfor %}
  </ul>

  {% include pagination.liquid %}
</div>
