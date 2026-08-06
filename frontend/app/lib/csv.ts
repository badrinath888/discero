import type { Transaction } from "./api";

function escapeCsvValue(
  value: string | number | boolean | null
): string {
  const normalized = value === null ? "" : String(value);
  return `"${normalized.replaceAll('"', '""')}"`;
}

export function transactionsToCsv(
  transactions: Transaction[]
): string {
  const rows = transactions.map((transaction) => [
    transaction.posted_on,
    transaction.description,
    transaction.merchant_name,
    transaction.category,
    (transaction.amount_cents / 100).toFixed(2),
    transaction.source,
    transaction.pending ? "Pending" : "Posted",
    transaction.account_name,
    transaction.institution_name,
  ]);

  return [
    [
      "Date",
      "Description",
      "Merchant",
      "Category",
      "Amount",
      "Source",
      "Status",
      "Account",
      "Institution",
    ],
    ...rows,
  ]
    .map((row) => row.map(escapeCsvValue).join(","))
    .join("\n");
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = filename;

  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
