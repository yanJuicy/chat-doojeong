import { useState } from "react";
import useLabelSuggestions from "../../hooks/useLabelSuggestions";
import { formatSize } from "../../utils/format";
import { replaceLastLabel, splitLabels } from "../../utils/labels";

export default function UploadItem({ item, onRemove, onChangeLabels }) {
  const [value, setValue] = useState("");
  const [suggestions, setSuggestions] = useLabelSuggestions(value);

  const addLabels = () => {
    const labels = splitLabels(value);
    if (!labels.length) return;
    onChangeLabels([...item.labels, ...labels]);
    setValue("");
    setSuggestions([]);
  };

  return (
    <article className="upload-item">
      <div className="upload-item-head">
        <div>
          <strong>{item.file.name}</strong>
          <span>{formatSize(item.file.size)}</span>
        </div>
        <button type="button" onClick={onRemove} aria-label={`${item.file.name} 제거`}>
          제거
        </button>
      </div>
      <div className="label-chips">
        {item.labels.length ? (
          item.labels.map((label) => (
            <span key={label}>
              {label}
              <button
                type="button"
                onClick={() => onChangeLabels(item.labels.filter((value) => value !== label))}
                aria-label={`${label} 라벨 제거`}
              >
                ×
              </button>
            </span>
          ))
        ) : (
          <small>라벨 없음 — 파일명이 검색 힌트로 사용됩니다.</small>
        )}
      </div>
      {!item.file.name.toLowerCase().endsWith(".zip") && (
        <div className="file-label-input">
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
              placeholder="이 파일의 라벨 추가"
              aria-label={`${item.file.name} 라벨 추가`}
            />
            {suggestions.length > 0 && (
              <div className="label-suggestions">
                {suggestions
                  .filter((label) => !item.labels.includes(label))
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
          <button type="button" onClick={addLabels} disabled={!value.trim()}>
            추가
          </button>
        </div>
      )}
    </article>
  );
}
