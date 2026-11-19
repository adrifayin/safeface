/**
 * English / Malayalam labels for investigator-facing screens (SRS NFR-U4).
 * The Malayalam strings are a first draft and must be reviewed by a native-speaking
 * officer before operational use. Legal texts (the screening caveat) are always shown
 * in English as well, so a translation can never replace the reviewed wording.
 */
import { createContext, useContext, useState, type ReactNode } from "react";

export type Lang = "en" | "ml";

const ML: Record<string, string> = {
  "Cases": "കേസുകൾ",
  "New case": "പുതിയ കേസ്",
  "Sign out": "പുറത്തുകടക്കുക",
  "Add evidence": "തെളിവ് ചേർക്കുക",
  "Open workbench": "പരിശോധന തുറക്കുക",
  "Questioned items": "പരിശോധിക്കേണ്ട ഇനങ്ങൾ",
  "Reference items": "താരതമ്യത്തിനുള്ള ഇനങ്ങൾ",
  "Case members": "കേസ് അംഗങ്ങൾ",
  "1. Kind of item": "1. ഇനത്തിന്റെ തരം",
  "2. Files (one or many — photos, videos, audio)": "2. ഫയലുകൾ (ഫോട്ടോ, വീഡിയോ, ഓഡിയോ)",
  "Drag files or a folder's contents here, or click to choose": "ഫയലുകൾ ഇവിടെ വലിച്ചിടുക, അല്ലെങ്കിൽ തിരഞ്ഞെടുക്കാൻ ക്ലിക്ക് ചെയ്യുക",
  "Hash & ingest": "ഹാഷ് ചെയ്ത് സൂക്ഷിക്കുക",
  "Preliminary automated screening": "പ്രാഥമിക സ്വയംചാലിത പരിശോധന",
  "doubt_raised": "സംശയം ഉയർന്നു — പരിശോധകനെ ഏൽപ്പിക്കുക",
  "no_doubt_raised": "പ്രവർത്തിച്ച സ്വയംചാലിത പരിശോധനകൾ സംശയം ഉയർത്തിയില്ല",
  "incomplete": "പ്രാഥമിക പരിശോധന പൂർത്തിയായിട്ടില്ല",
  "caveat": "ഇത് ഒരു കണ്ടെത്തലല്ല. ഈ ഉപകരണങ്ങൾക്ക് കൃത്യതയിൽ പരിമിതികളുണ്ട്: യഥാർത്ഥ ചിത്രങ്ങളിൽ തെറ്റായ മുന്നറിയിപ്പും കൃത്രിമമായവ കണ്ടെത്താതിരിക്കലും സംഭവിക്കാം. പരിശീലനം ലഭിച്ച പരിശോധകനെ ഏൽപ്പിക്കണോ എന്ന് തീരുമാനിക്കാൻ മാത്രം ഉപയോഗിക്കുക; ആരെയും കുറ്റപ്പെടുത്താൻ ഉപയോഗിക്കരുത്.",
  "Evidence integrity": "തെളിവിന്റെ സമഗ്രത",
  "Verified — unchanged since it was received": "സ്ഥിരീകരിച്ചു — ലഭിച്ചതിനുശേഷം മാറ്റമില്ല",
};

const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({ lang: "en", setLang: () => {} });

function initial(): Lang {
  try {
    return window.localStorage.getItem("safeface.lang") === "ml" ? "ml" : "en";
  } catch {
    return "en";
  }
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initial);
  const setLang = (l: Lang) => {
    setLangState(l);
    try {
      window.localStorage.setItem("safeface.lang", l);
    } catch {
      /* preference only */
    }
  };
  return <LangContext.Provider value={{ lang, setLang }}>{children}</LangContext.Provider>;
}

export function useLang() {
  return useContext(LangContext);
}

/** Translate a label; falls back to English when there is no Malayalam entry. */
export function useT(): (key: string, english?: string) => string {
  const { lang } = useLang();
  return (key, english) => (lang === "ml" && ML[key] ? ML[key] : english ?? key);
}
