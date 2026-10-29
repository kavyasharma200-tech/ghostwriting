// Who is a ghost talking to? Plain rules decide. (Gemma 3 1B was tried as the judge and wasn't reliable at
// that size: it copied the prompt's example or said yes to everything. It is the witness instead.)

const AI = "(?:llms?|large language models?|language models?|ai|assistants?|chatbots?|chatgpt|gpt-?\\d\\w*|claude|gemini|copilot)";

const RULES = [
  [/\b(ignore|disregard|forget)\b[^.]{0,30}\b(previous|prior|above|earlier|all|the user'?s?)\b[^.]{0,20}\b(instructions?|prompts?|rules?|context|questions?|requests?)\b/i, "tells the AI to drop its instructions"],
  [/\b(llms?|large language models?|language models?|ai (reviewers?|reviewing|assistants?|models?|systems?|agents?|graders?|screeners?|screening|reading|summari[sz]ing)|chatgpt|gpt-?\d|claude|gemini|copilot|chatbot)\b/i, "addresses an AI by name"],
  // "AI résumé screeners", "Note to the LLM", "Assistant, ignore…". A colon after a bare name is left out:
  // chat transcripts in figures are full of "Assistant:".
  [new RegExp(`\\bai(\\s+[a-z]+){0,2}\\s+(reviewers?|screeners?|readers?|graders?|summari[sz]ers?)\\b|\\bnote to (the |any )?${AI}\\b|^\\s*${AI}\\s*,`, "i"), "addresses an AI by name"],
  [/\b(you are|act as|pretend to be|as an?) (an? )?(ai|assistant|reviewer|grader|recruiter|language model)\b/i, "gives the AI a role"],
  [/\b(positive review|give (a|this) (positive|high|top|good)|recommend (accepting|acceptance|this)|accept this (paper|submission)|score (this|it) (highly|10)|rate (this|it|me) (highly|10|5)|five stars?)/i, "asks for a good verdict"],
  [/\b(hire|shortlist|top candidate|best candidate|strongest candidate|highly qualified|strong(ly)? recommend (this|the) candidate|rank [^.]{0,40}\bfirst)\b/i, "asks to favour a candidate"],
  [/\b(do not|don't|never) (mention|reveal|tell|disclose|summari[sz]e)\b/i, "asks the AI to keep something from you"],
  [/\b(system prompt|new instructions|instead,? (say|write|reply|respond)|(reply|respond|answer) only\b|when (asked|summari[sz]ing)\b[^.]{0,40}\b(say|reply|respond|answer|tell)\b)/i, "tries to rewrite the AI's instructions"],
];

export function rules(text) {
  const hits = [...new Set(RULES.filter(([re]) => re.test(text)).map(([, why]) => why))];
  return { talksToAi: hits.length > 0, hits };
}

/**
 * Most hidden-looking text in ordinary papers is a figure label on a coloured box, a maths symbol or the
 * arXiv stamp down the margin. Under five real words, saying nothing to an AI: counted, not headlined.
 */
export function minor(text) {
  if (rules(text).talksToAi) return false;
  if (/^arXiv:\d/i.test(text.trim())) return true;
  return (text.match(/[A-Za-z]{3,}/g) || []).length < 5;
}
