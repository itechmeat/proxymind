import type { Content, Html, Parent, Root, Text } from "mdast";
import type { Plugin } from "unified";
import { visit } from "unist-util-visit";

import type { CitationResponse } from "@/types/chat";

interface RemarkCitationsOptions {
  citations?: CitationResponse[] | null;
  enabled?: boolean;
}

const CITATION_PATTERN = /\[source:(\d+)\]/g;

function createCitationHtml(citationIndex: number): Html {
  return {
    type: "html",
    value: `<sup><button class="citation-ref" data-citation-index="${citationIndex}" aria-label="Jump to source ${citationIndex}" type="button">${citationIndex}</button></sup>`,
  };
}

function splitTextWithCitations(
  value: string,
  validIndexes: Set<number>,
): Content[] {
  const nodes: Content[] = [];
  let previousOffset = 0;

  for (const match of value.matchAll(CITATION_PATTERN)) {
    const marker = match[0];
    const rawIndex = match[1];
    const index = match.index ?? -1;

    if (index < 0) {
      continue;
    }

    const citationIndex = Number(rawIndex);
    const isValidCitation = validIndexes.has(citationIndex);

    if (previousOffset < index) {
      nodes.push({
        type: "text",
        value: value.slice(previousOffset, index),
      });
    }

    nodes.push(
      isValidCitation
        ? createCitationHtml(citationIndex)
        : {
            type: "text",
            value: marker,
          },
    );

    previousOffset = index + marker.length;
  }

  if (nodes.length === 0) {
    return [];
  }

  if (previousOffset < value.length) {
    nodes.push({
      type: "text",
      value: value.slice(previousOffset),
    });
  }

  return nodes;
}

export const remarkCitations: Plugin<[RemarkCitationsOptions?], Root> = (
  options,
) => {
  const citations = options?.citations ?? [];
  const enabled = options?.enabled ?? true;
  const validIndexes = new Set(citations.map((citation) => citation.index));

  return (tree) => {
    if (!enabled || validIndexes.size === 0) {
      return;
    }

    visit(tree, "text", (node: Text, index, parent: Parent | undefined) => {
      if (index === undefined || !parent) {
        return;
      }

      const replacementNodes = splitTextWithCitations(node.value, validIndexes);
      if (replacementNodes.length === 0) {
        return;
      }

      parent.children.splice(index, 1, ...replacementNodes);
      return index + replacementNodes.length;
    });
  };
};
