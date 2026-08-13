export function uniqueLabels(values) {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

export function splitLabels(value) {
  return uniqueLabels(value.split(","));
}

export function replaceLastLabel(value, label) {
  const parts = value.split(",");
  parts[parts.length - 1] = label;
  return `${parts.map((part) => part.trim()).filter(Boolean).join(", ")}, `;
}
