import i18n from "i18next";
import { initReactI18next, useTranslation } from "react-i18next";

import { appLanguage } from "@/lib/config";
import en from "@/locales/en";
import type {
  CatalogItemType,
  SnapshotStatus,
  SourceStatus,
  SourceType,
} from "@/types/admin";

const resources = {
  en: {
    translation: en,
  },
} as const;

if (!i18n.isInitialized) {
  void i18n.use(initReactI18next).init({
    lng: resources[appLanguage as keyof typeof resources] ? appLanguage : "en",
    fallbackLng: "en",
    initImmediate: false,
    resources,
    interpolation: {
      escapeValue: false,
    },
    react: {
      useSuspense: false,
    },
  });
}

export function useAppTranslation() {
  return useTranslation();
}

export function translate(key: string, values?: Record<string, unknown>) {
  return i18n.t(key, values);
}

export function translateSourceStatus(status: SourceStatus) {
  return translate(`admin.source.status.${status}`);
}

export function translateSnapshotStatus(status: SnapshotStatus) {
  return translate(`admin.snapshot.status.${status}`);
}

export function translateSourceType(sourceType: SourceType) {
  return translate(`admin.source.type.${sourceType}`);
}

export function translateCatalogItemType(itemType: CatalogItemType) {
  return translate(`admin.catalog.type.${itemType}`);
}

export default i18n;
