import { useState } from "react";
import useLabelSuggestions from "../../hooks/useLabelSuggestions";
import { replaceLastLabel, splitLabels } from "../../utils/labels";

export default function CommonLabelInput({ onApply }) {
  const [value, setValue] = useState("");
  const [suggestions, setSuggestions] = useLabelSuggestions(value);

  const apply = () => {
    const labels = splitLabels(value);
    if (!labels.length) return;
    onApply(labels);
    setValue("");
    setSuggestions([]);
  };

  return (
    <div className="common-labels">
      <div className="label-input-wrap">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              apply();
            }
          }}
          placeholder="전체 파일에 적용할 라벨 (쉼표로 구분)"
          aria-label="공통 라벨"
        />
        {suggestions.length > 0 && (
          <div className="label-suggestions">
            {suggestions.map((label) => (
              <button
                type="button"
                key={label}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setValue((current) => replaceLastLabel(current, label))}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
      <button type="button" onClick={apply} disabled={!value.trim()}>
        전체 적용
      </button>
    </div>
  );
}
