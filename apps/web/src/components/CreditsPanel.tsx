"use client";
import { useEffect, useState } from "react";
import { describeError, type Api, type LedgerEntry, type Me } from "@/lib/api";

const KIND: Record<string, string> = {
  grant: "Credits added",
  purchase: "Purchase",
  reserve: "Held for a generation",
  capture: "Generation completed",
  release: "Returned (not charged)",
  refund: "Refund",
  adjustment: "Adjustment",
};

export default function CreditsPanel({ api, me, refreshKey }: { api: Api; me: Me | null; refreshKey: number }) {
  const [items, setItems] = useState<LedgerEntry[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api
      .ledger()
      .then((l) => {
        if (live) setItems(l.items);
      })
      .catch((e) => {
        if (live) setProblem(describeError(e));
      });
    return () => {
      live = false;
    };
  }, [api, refreshKey]);

  return (
    <div className="stack">
      <div className="balance">
        <div>
          <div className="balance-num">{me?.credits.balance ?? "—"}</div>
          <div className="muted">credits available</div>
        </div>
        <div className="muted small">
          {me?.credits.reserved ? `${me.credits.reserved} held by running generations. ` : ""}
          One generation costs {me?.price.image_to_3d ?? "—"} credits. A generation that fails or is cancelled is not charged.
        </div>
      </div>
      {problem && (
        <div className="err" role="alert">
          {problem}
        </div>
      )}
      {items && items.length === 0 && <p className="muted">No credit activity yet.</p>}
      {items && items.length > 0 && (
        <table className="ledger">
          <thead>
            <tr>
              <th scope="col">What</th>
              <th scope="col" className="num">
                Change
              </th>
              <th scope="col" className="num">
                Balance
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.entry_id}>
                <td>
                  {KIND[e.kind] ?? e.kind}
                  <div className="muted small">{e.at ? new Date(e.at).toLocaleString() : ""}</div>
                </td>
                <td className={`num ${e.amount > 0 ? "pos" : e.amount < 0 ? "neg" : ""}`}>{e.amount > 0 ? `+${e.amount}` : e.amount === 0 ? "—" : e.amount}</td>
                <td className="num">{e.balance_after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
