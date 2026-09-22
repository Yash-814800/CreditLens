function parseCsvLine(line: string): string[] {
  const result: string[] = []
  let cur = ''
  let inQuotes = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (c === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"'
        i++
      } else {
        inQuotes = !inQuotes
      }
    } else if (c === ',' && !inQuotes) {
      result.push(cur.trim())
      cur = ''
    } else {
      cur += c
    }
  }
  result.push(cur.trim())
  return result
}

export interface ParsedCsvStatement {
  metadata: Array<{ key: string; value: string }>
  headers: string[]
  rows: string[][]
}

export function parseCsvStatement(text: string): ParsedCsvStatement {
  const lines = text.trim().split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
  const metadata: Array<{ key: string; value: string }> = []
  let tableHeaderIndex = -1

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const parts = parseCsvLine(line)
    const lower = parts.map((p) => p.toLowerCase())
    if (
      parts.length >= 3 &&
      (lower.includes('date') || lower.includes('narration') || lower.includes('balance') || lower.includes('description'))
    ) {
      tableHeaderIndex = i
      break
    }
    if (parts.length === 2 && !lower.includes('date')) {
      metadata.push({
        key: parts[0].replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
        value: parts[1],
      })
    }
  }

  if (tableHeaderIndex === -1) {
    if (lines.length === 0) return { metadata: [], headers: [], rows: [] }
    const headers = parseCsvLine(lines[0])
    const rows = lines.slice(1).map(parseCsvLine)
    return { metadata, headers, rows }
  }

  const headers = parseCsvLine(lines[tableHeaderIndex])
  const rows = lines.slice(tableHeaderIndex + 1).map(parseCsvLine)
  return { metadata, headers, rows }
}

