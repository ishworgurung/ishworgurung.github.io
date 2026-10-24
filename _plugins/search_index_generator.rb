# Full-text search index for assets/js/search-fulltext.js.
#
# Built from each post's rendered HTML (document.content, captured right
# after Jekyll converts and renders it -- not the raw Markdown, and not the
# layout-wrapped page), so the section ids below are exactly the ids
# kramdown gave the real headings on the page: no separate slugify pass to
# keep in sync. Splitting by heading means a search hit can link straight
# to the right section instead of the top of the post.
require "nokogiri"
require "json"

module Site
  module SearchIndex
    HEADING_TAGS = %w[h2 h3 h4].freeze

    SECTIONS = []

    module_function

    def collect(doc)
      return unless doc.collection && doc.collection.label == "posts"

      fragment = Nokogiri::HTML::DocumentFragment.parse(doc.content)
      SECTIONS.concat(sections_for(doc, fragment))
    end

    def write(site)
      dest = File.join(site.dest, "assets", "search-index.json")
      FileUtils.mkdir_p(File.dirname(dest))
      File.write(dest, JSON.generate(SECTIONS))
    end

    # One entry per heading-delimited section (plus a leading section for
    # anything before the first heading). `id` is the heading's real id
    # attribute, so url + "#" + id lands exactly where the text is.
    def sections_for(doc, fragment)
      sections = [{ "id" => nil, "heading" => nil, "text" => +"" }]

      fragment.children.each do |node|
        if node.element? && HEADING_TAGS.include?(node.name)
          sections << { "id" => node["id"], "heading" => node.text.strip, "text" => +"" }
          next
        end

        text = node.text
        next if text.nil? || text.strip.empty?

        sections.last["text"] << " " << text
      end

      sections.filter_map do |s|
        body = normalize(s["text"])
        next if body.length < 40 # skip near-empty sections (e.g. a lone figure)

        url = doc.url
        url += "##{s['id']}" if s["id"]

        {
          "title" => doc.data["title"],
          "url" => url,
          "date" => doc.date.strftime("%b %Y"),
          "heading" => s["heading"],
          "body" => body,
        }
      end
    end

    def normalize(text)
      text.gsub(/\s+/, " ").strip
    end
  end
end

Jekyll::Hooks.register(:site, :after_reset) { Site::SearchIndex::SECTIONS.clear }
Jekyll::Hooks.register(:documents, :post_render) { |doc| Site::SearchIndex.collect(doc) }
Jekyll::Hooks.register(:site, :post_write) { |site| Site::SearchIndex.write(site) }
