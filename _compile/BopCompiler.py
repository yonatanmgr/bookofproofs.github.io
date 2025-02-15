import re
import markdown
import time

from FileMgr import FileMgr
from BopSource import BopSource, BopLayouts
from BopReferences import BopReferences
from BopValidator import BopValidator
from BopIndexCompiler import BopIndexCompiler
from BopValidationError import BopValidationError


class BopCompiler:
    local = False
    verbose = False
    generate_indices_locally = False  # defaults to False, when local == True

    # (this will skip index generation to improve performance of compilation)
    # If amended to True, please set to False again when checking in a pull request.

    def __init__(self):
        self.fm = FileMgr()
        self.templates = dict()
        self._main_template = ""
        self.sources = dict()
        self.indices = dict()
        self._source_references = None
        self.references = None
        self._source_licenses = list()
        self._source_licenses_ids = set()
        self._load_templates()
        self._validator = None
        self._index_compiler = None

    def _load_templates(self):
        templates = self.fm.get_folder_content("_compile/_templates")
        for template in templates:
            self.templates[template] = self.fm.get_file_content("_compile/_templates", template)

    def compile(self):
        self.fm.clear_docs()
        self._main_template = self.templates["main.html"]
        self._main_template = self._main_template.replace("{{ meta }}", self.templates["meta.html"])
        self._main_template = self._main_template.replace("{{ header }}", self.templates["header.html"])
        self._main_template = self._main_template.replace("{{ footer }}", self.templates["footer.html"])
        self._compile_sources()
        self._compile_assets()

    def _compile_sources(self):
        self.prepare_all_sources()
        self.references = BopReferences(self._source_references, self._source_licenses)
        self._validate_all_sources()
        self._making_all_indices()
        self._render_all_sources()
        if BopCompiler.local:
            self._make_local()
        self._write_compiled_sources()
        self._write_sitemap()

    def _make_local(self):
        print("   Making sources local...")
        for source in self.sources:
            bop_source = self.sources[source]
            content_replaced = bop_source.get_compiled_content()
            project_root = str(FileMgr.get_project_folder()).replace("\\", "/")
            content_replaced = content_replaced.replace(BopSource.url_root, project_root + "/docs")
            # replace image urls starting with the root url to local
            content_replaced = content_replaced.replace(BopSource.url_images, project_root + "/_sources")
            bop_source.set_compiled_content(content_replaced)

    def _write_compiled_sources(self):
        print("Writing compiled sources...")
        for source in self.sources:
            bop_source = self.sources[source]
            if bop_source.layout != BopLayouts.hidden:
                file_destination = bop_source.get_file_destination()
                self.fm.write_file(file_destination, bop_source.name + ".html", bop_source.get_compiled_content())

    def _render_references(self, bop_source: BopSource):
        references_md = "<hr>\n"
        has_references = False
        has_footnotes = False
        licenses = self.references.get_licenses_for_bop_source(bop_source)
        if len(licenses) > 0:
            references_md += "### References\n"
        for lic in licenses:
            has_references = True
            bop_license = licenses[lic]
            references_md += "\n#### " + bop_license.license_source.title + "\n\n"
            for reference_id in bop_license.references:
                references_md += "1. " + bop_license.references[reference_id] + "\n"
            body_of_reference = bop_license.license_source.get_body()
            if body_of_reference != "":
                references_md += "\n" + body_of_reference + "\n"

        if re.search(r"\[\^.*?\]", bop_source.get_pre_body() + "\n" + bop_source.get_body()):
            has_references = True
            has_footnotes = True
        if has_footnotes:
            references_md += "\n#### Footnotes\n"
        if has_references:
            return references_md
        else:
            return ""

    def _get_contributors(self, bop_source):
        cc_by_sa = self.references.get_cc_by_sa()
        references_md = "<hr>\n"

        improve_this_site_html = " <a class='improve' title='{0}' href='{1}/{2}'>{3}</a>".format(
            'improve this site',
            BopSource.url_images,
            bop_source.get_file_destination() + "/" + bop_source.name + ".md",
            "<img src='{0}/_assets/images/edit-black.png?raw=true' alt=''>".format(BopSource.url_images))
        improvement_history_html = " <a class='improve' title='{0}' href='{1}/{2}'>{3}</a>".format(
            'improvement history',
            BopSource.url_commits,
            bop_source.get_file_destination() + "/" + bop_source.name + ".md",
            "<img src='{0}/_assets/images/calendar-black.png?raw=true' alt=''>".format(BopSource.url_images))
        references_md += "<span class='navigation'>{0}[{1}][ccbysa]!</span> {2} {3}<br>".format(
            "Thank you to the contributors under ", "CC BY-SA 4.0", improve_this_site_html,
            improvement_history_html)
        references_md += bop_source.get_contributors()
        references_md += "<br>\n\n"
        references_md += "[ccbysa]:" + cc_by_sa.publisher + "\n"
        return references_md

    def prepare_all_sources(self):
        print("Preparing all sources...")
        sources = self.fm.get_folder_content_rek()
        for file in sources:
            if "_sources/_references/references.md" in file:
                bop_source = BopSource(file)
                self._source_references = bop_source
            elif "_sources/_licenses" in file:
                bop_source = BopSource(file)
                self._source_licenses.append(bop_source)
                if bop_source.nodeid in self._source_licenses_ids:
                    raise BopValidationError("LICENSE", "01",
                                             "Duplicate license " + bop_source.nodeid + " in " +
                                             bop_source.get_file_name())
                else:
                    self._source_licenses_ids.add(bop_source.nodeid)
            else:
                bop_source = BopSource(file)
            self.sources[file] = bop_source

    def _validate_all_sources(self):
        print("Validating sources...")
        self._validator = BopValidator(self.sources)
        self._index_compiler = BopIndexCompiler(self._validator)

    def _making_all_indices(self):
        if not self.local:
            self.__making_all_indices()
        else:
            if self.generate_indices_locally:
                self.__making_all_indices()
            else:
                print("   Skipping local compilation of all index html files for performance reasons.")

    def __making_all_indices(self):
        print("   Making tree index")
        self.indices["{{ tree-index }}"] = self._index_compiler.get_tree_index()
        print("   Making building block index")
        self.indices["{{ bb-index }}"] = self._index_compiler.get_building_block_index()
        self.indices["{{ bbo-index }}"] = self._index_compiler.get_other_building_block_index()
        self.indices["{{ bbh-index }}"] = self._index_compiler.get_history_building_block_index()
        print("   Making issue index")
        self.indices["{{ q-index }}"] = self._index_compiler.get_issue_index()
        print("   Making contributors index (github users)")
        self.indices["{{ cg-index }}"] = self._index_compiler.get_github_contributors_index()
        print("   Making contributors index (non-github users)")
        self.indices["{{ cng-index }}"] = self._index_compiler.get_non_github_contributors_index()
        print("   Making interactive widgets index")
        self.indices["{{ w-index }}"] = self._index_compiler.get_widgets_index()
        print("   Making sourcecode index")
        self.indices["{{ sc-index }}"] = self._index_compiler.get_sourcecode_index()
        print("   Making person index (by name)")
        self.indices["{{ pbn-index }}"] = self._index_compiler.get_person_index_by_name()
        print("   Making person index (by birth year)")
        self.indices["{{ pby-index }}"] = self._index_compiler.get_person_index_by_birth_year()
        print("   Making person index (by tag)")
        self.indices["{{ pbt-index }}"] = self._index_compiler.get_person_index_by_tag()
        print("   Making keywords index")
        self.indices["{{ ii-index }}"] = self._index_compiler.get_keywords_index()

    def _render_all_sources(self):
        print("Rendering sources...")
        self._render_all_references()
        self._render_all_tocs()
        self._render_all_markdowns()

    def _render_all_tocs(self):
        print("   Rendering tables of content")
        pc = self._validator.get_parent_child_graph()
        nodes = self._validator.get_nodes()
        for parentid in pc:
            self.__create_toc(parentid, self.__collect_children_for_toc(pc, nodes, parentid), nodes)

    def __collect_children_for_toc(self, pc: dict, nodes: dict, parentid: str):
        distinct_related_tocs = dict()
        pc[parentid].sort(key=self._validator.get_order_id)
        for child in pc[parentid]:
            bop_source = nodes[child]
            if bop_source.layout in BopSource.related_layouts:
                title = BopSource.get_plural_layout_title(bop_source.layout)
                if title not in distinct_related_tocs:
                    distinct_related_tocs[title] = list()
                distinct_related_tocs[title].append(child)
            else:
                if bop_source.title in distinct_related_tocs:
                    AssertionError("Title '{0}' used in {1} was already used among siblings {2}".format(
                        bop_source.title,
                        bop_source.get_file_name(),
                        str(distinct_related_tocs[bop_source.title])
                    ))
                else:
                    distinct_related_tocs[bop_source.title] = bop_source
        return distinct_related_tocs

    def __create_toc(self, parentid: str, distinct_related_tocs: dict, nodes: dict):
        toc = ""
        bop_source = nodes[parentid]
        if bop_source.layout not in [BopLayouts.default, BopLayouts.index, BopLayouts.hidden]:
            toc += "<h3 class='navigation'>Table of Contents</h3>\n\n"
            # first, create a toc of related nodes
            for title in distinct_related_tocs:
                if isinstance(distinct_related_tocs[title], list):
                    toc += title + ": "
                    counter = 0
                    for node_id in distinct_related_tocs[title]:
                        counter += 1
                        bop_source1 = nodes[node_id]
                        toc += "<a href='{0}'>{1}</a> ".format(bop_source1.url(), counter)
            # now, create a list of other subnodes
            toc += "\n\n"
            counter = 0
            for title in distinct_related_tocs:
                if isinstance(distinct_related_tocs[title], BopSource):
                    counter += 1
                    bop_source1 = distinct_related_tocs[title]
                    toc += str(counter) + ". <a href='{0}'>{1}</a>\n".format(bop_source1.url(),
                                                                             bop_source1.get_plane_long_title())
        bop_source.set_toc(toc)

    def _render_all_references(self):
        print("   Rendering references")
        for source in self.sources:
            bop_source = self.sources[source]
            if bop_source.layout != BopLayouts.default:
                references_md = self._get_contributors(bop_source)
                references_md += self._render_references(bop_source)
                bop_source.set_references_md(references_md)

    def _render_all_markdowns(self):
        print("   Rendering markdowns")
        for source in self.sources:
            start_time = time.time()
            bop_source = self.sources[source]
            content_replaced = self._replace_template(self._main_template, bop_source)
            if bop_source.parent is not None and bop_source.parent.nodeid == 'bookofproofs$i':
                content_replaced = self._replace_indices(content_replaced)
            bop_source.set_compiled_content(content_replaced)
            if BopCompiler.verbose:
                print("            {0}s: {1}".format("%.2f" % (time.time() - start_time), source))

    def _replace_indices(self, content_replaced: str):
        for index in self.indices:
            content_replaced = content_replaced.replace(index, self.indices[index])
        return content_replaced

    def _replace_template(self, content, bop_source):
        body = ""
        if len(bop_source.categories) > 0:
            body += bop_source.get_categories_links() + "\n"
        body += bop_source.get_content_of_node() + "\n"
        body += bop_source.get_toc() + "\n"
        if bop_source.layout == BopLayouts.person:
            body += bop_source.get_relevant_tags_html() + "\n"
        body += bop_source.get_referencing_nodes_html() + "\n"
        body += bop_source.get_references_md()
        body += bop_source.get_link_references()

        content_replaced = content.replace("{{ body }}",
                                           markdown.markdown(body, tab_length=2,
                                                             extensions=['pymdownx.magiclink', 'tables', 'footnotes',
                                                                         'def_list']))
        content_replaced = self._make_tables_responsive(content_replaced)
        content_replaced = content_replaced.replace("{{ keywords }}", ",".join(bop_source.keywords))
        content_replaced = content_replaced.replace("{{ description }}", bop_source.description)
        content_replaced = content_replaced.replace("{{ title }}", bop_source.title)
        content_replaced = self._replace_scripts(content_replaced, bop_source)
        content_replaced = self._escape_mathjax(r'<code>(\$.*?\$)</code>', content_replaced)
        content_replaced = self._escape_mathjax(r'<code>(\\\(.*?\\\))</code>', content_replaced)
        content_replaced = self._escape_mathjax(r'<code>(\\\[.*?\\\])</code>', content_replaced)
        return content_replaced

    def _compile_assets(self):
        print("Compiling assets...")
        self._compile_sub_assets("css")
        self._compile_sub_assets("js")
        self._compile_sub_assets("jquery-ui")
        self.fm.copy_folder("../_sources/_assets/jquery-ui/images", "../docs/assets/jquery-ui/images")
        # Do not uncomment this. To save storage, we will store images only once in the source github repository
        # but not as a duplicate in the docs folder store. As a convention, all images' urls will refer to the source
        # self.fm.copy_folder("../_sources/_assets/images", "../docs/assets/images")
        self.fm.copy_file("../_sources/_assets/images/fav.ico", "../docs/fav.ico")
        # google site verification
        self.fm.copy_file("../_sources/_assets/other/google5e9ab19be7343012.html",
                          "../docs/google5e9ab19be7343012.html")
        # fpl syntax diagrams
        self.fm.copy_file("../_sources/_assets/other/FPLSyntaxDiagrams.xhtml", "../docs/FPLSyntaxDiagrams.html")

    def _compile_sub_assets(self, sub):
        sub_contents = self.fm.get_folder_content("_sources/_assets/" + sub)
        for file in sub_contents:
            content = self.fm.get_file_content("_sources/_assets/" + sub, file)
            if file == "bop.js":
                search_links = self._index_compiler.get_search_autocomplete_index()
                content = content.replace("{{ search-links }}", search_links)
                content = content.replace("{{ url }}", BopSource.url_root)
                if BopCompiler.local:
                    project_root = "file:///" + str(FileMgr.get_project_folder()).replace("\\", "/")
                    content = content.replace(BopSource.url_root, project_root + "/docs")
            self.fm.write_file("assets/" + sub, file, content)

    @staticmethod
    def _make_tables_responsive(content: str):
        pattern = re.compile(r"(<table>.*<\/table>)", flags=re.S)
        replaced = re.sub(pattern, r"<div style='overflow-x:auto;'>\1</div>", content)
        return replaced

    def _replace_scripts(self, content: str, bop_source: BopSource):
        pattern = re.compile(r'<p>(§§§\d+)</p>')
        for match in pattern.finditer(content):
            key = match.group(1)
            if key in bop_source.scripts:
                script = bop_source.scripts[key]
                if bop_source.script_has_python(script):
                    script = markdown.markdown(script, tab_length=3,
                                               extensions=['codehilite', 'fenced_code'])
                else:
                    script = re.sub(r"(^```[a-z]*$)", r"", script, flags=re.M)
                content = content.replace("<p>" + key + "</p>", "\n" + script + "\n")
            else:
                AssertionError("Script key {0} not found in {1}".format(key, bop_source.get_file_name()))
        return content

    def _escape_mathjax(self, pattern_string: str, content: str):
        pattern = re.compile(pattern_string, flags=re.S)
        new_content = content
        for match in pattern.finditer(content):
            new_content = new_content.replace("<code>" + match.group(1) + "</code>", match.group(1))
        return new_content

    def _write_sitemap(self):
        sitemaps = list()
        for source in self.sources:
            bop_source = self.sources[source]
            if bop_source.layout not in [BopLayouts.hidden, BopLayouts.default]:
                url = bop_source.url()
                if url == "https://bookofproofs.github.io/index.html":
                    url = "https://bookofproofs.github.io/"
                    sitemaps.append(url)
                elif "https://bookofproofs.github.io/branches/" in url or \
                        "https://bookofproofs.github.io/history/" in url:
                    sitemaps.append(url)
        sitemaps.sort(key=lambda x: len(x))
        sitemap = "\n".join(sitemaps)
        self.fm.write_file("", "sitemap.txt", sitemap)

    def get_validator(self):
        return self._validator
