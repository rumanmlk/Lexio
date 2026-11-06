/**
 * A small most-recently-used cache whose values are shared by whoever holds them. A value that is in use
 * is never evicted (or destroyed), so opening a few more documents cannot pull one out from under the
 * pane that is showing it. Once released, it is the first to go when the cache is over its size.
 */
export class RefCache<V> {
  private entries = new Map<string, { value: V; refs: number }>();
  private create: (key: string) => V;
  private destroy: (value: V) => void;
  private max: number;

  constructor(create: (key: string) => V, destroy: (value: V) => void, max: number) {
    this.create = create;
    this.destroy = destroy;
    this.max = max;
  }

  get size(): number {
    return this.entries.size;
  }

  /** The value for `key`, made if needed. Call `release` when finished with it. */
  acquire(key: string): { value: V; release: () => void } {
    let entry = this.entries.get(key);
    if (entry) this.entries.delete(key);
    else entry = { value: this.create(key), refs: 0 };
    this.entries.set(key, entry); // most recently used goes last
    entry.refs++;
    this.trim();
    const held = entry;
    let released = false;
    return {
      value: entry.value,
      release: () => {
        if (released) return;
        released = true;
        held.refs--;
        this.trim();
      },
    };
  }

  /** Drops a value that turned out to be unusable, so the next `acquire` makes a new one. */
  forget(key: string, value: V): void {
    const entry = this.entries.get(key);
    if (entry?.value === value) this.entries.delete(key);
    this.destroy(value);
  }

  private trim(): void {
    for (const [key, entry] of this.entries) {
      if (this.entries.size <= this.max) return;
      if (entry.refs > 0) continue;
      this.entries.delete(key);
      this.destroy(entry.value);
    }
  }
}
