import { useEffect, useState } from "react";
import useLabelSuggestions from "../../hooks/useLabelSuggestions";
import { replaceLastLabel, splitLabels, uniqueLabels } from "../../utils/labels";

export default function LabelEditor({ labels, onSave, disabled }) {
  const [currentLabels, setCurrentLabels] = useState(labels);
  const [value, setValue] = useState("");
  const [suggestions, setSuggestions] = useLabelSuggestions(value);

  useEffect(() => setCurrentLabels(labels), [labels]);

  const addLabels = () => {
    const next = splitLabels(value);
    if (!next.length) return;
    setCurrentLabels((current) => uniqueLabels([...current, ...next]));
    setValue("");
    setSuggestions([]);
  };

  return (
    <section className="detail-section">
      <div className="detail-section-heading">
        <div>
          <b>검색 라벨</b>
          <span>수정하면 기존 청크와 벡터가 자동으로 다시 생성됩니다.</span>
        </div>
        <button type="button" onClick={() => onSave(currentLabels)} disabled={disabled}>
          라벨 저장
        </button>
      </div>
      <div className="label-chips detail-label-chips">
        {currentLabels.length ? currentLabels.map((label) => (
          <span key={label}>
            {label}
            <button
              type="button"
              onClick={() => setCurrentLabels((current) => current.filter((item) => item !== label))}
              aria-label={`${label} 라벨 제거`}
              disabled={disabled}
            >
              ×
            </button>
          </span>
        )) : <small>라벨이 없습니다.</small>}
      </div>
      <div className="detail-label-input">
        <div className="label-input-wrap">
          <input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addLabels();
              }
            }}
            placeholder="추가할 라벨 입력"
            disabled={disabled}
          />
          {suggestions.length > 0 && (
            <div className="label-suggestions">
              {suggestions
                .filter((label) => !currentLabels.includes(label))
                .map((label) => (
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
        <button type="button" onClick={addLabels} disabled={disabled || !value.trim()}>
          추가
        </button>
      </div>
    </section>
  );
}
