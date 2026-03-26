import type { Schema } from "hast-util-sanitize";
import { defaultSchema } from "rehype-sanitize";

export const citationSanitizeSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), "button"],
  attributes: {
    ...defaultSchema.attributes,
    button: [
      ...((defaultSchema.attributes?.button ?? []) as NonNullable<
        NonNullable<Schema["attributes"]>["button"]
      >),
      ["className", "citation-ref"],
      "dataCitationIndex",
      "ariaLabel",
      ["type", "button"],
    ],
  },
} satisfies Schema;
