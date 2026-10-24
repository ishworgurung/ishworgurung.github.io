---
title: "Google's Rust style guide, and the case for just writing the loop"
---

A short plug for two things I have been reading: Google's [Rust Style Guide](https://google.github.io/styleguide/rustguide.html), and [BeautifulRust](https://github.com/morganlinton/BeautifulRust), which builds on it.

## 🦀 The guide

Google uses Rust across google3, Android, ChromeOS, Fuchsia and Chrome, and the guide is how they keep that code consistent. It is short for a style guide, precise, and practical. Most rules are a heading, a sentence or two of reasoning, and a code example, so you can read it in one sitting and use it the next day. It also says up front what it is for: readability and maintainability over writeability, and staying consistent with the wider Rust ecosystem instead of inventing a house dialect.

A lot of it clicked for me: prefer borrows over deep copies, [`enum`](https://doc.rust-lang.org/std/keyword.enum.html) over [`bool`](https://doc.rust-lang.org/std/primitive.bool.html) in APIs, [`expect`](https://doc.rust-lang.org/std/result/enum.Result.html#method.expect) over [`unwrap`](https://doc.rust-lang.org/std/result/enum.Result.html#method.unwrap), pattern matching over check-then-unwrap, no glob imports. None of it is surprising, and that is the point. It writes down what good Rust already looks like.

## 🔁 The one that clicked hardest

One section is titled "Don't use iterator combinator chains when direct iteration is clearer", and it names something I see fellow Rustaceans do all the time. This is the guide's own example:

```rust
let mut error_count = 0;
let _processed_items: Vec<_> = items
    .into_iter()
    .map(transformation_that_may_fail)
    .map(|result| {
        if result.is_err() {
            error_count += 1;
        }
        result
    })
    .filter_map(Result::ok)
    .collect();
```

Every line is idiomatic on its own, and together they are hard to read. A closure in the middle of the chain changes a counter outside it. One [`.map`](https://doc.rust-lang.org/std/iter/trait.Iterator.html#method.map) doesn't map at all, it just looks at each value and passes it on. The real work, sorting successes from failures, is spread across three adapters. Even Clippy notices: it warns that a [`.map`](https://doc.rust-lang.org/std/iter/trait.Iterator.html#method.map) which only peeks at its value should be an [`.inspect`](https://doc.rust-lang.org/std/iter/trait.Iterator.html#method.inspect).

Here is the same logic as a loop:

```rust
let mut error_count = 0;
let mut processed_items = Vec::with_capacity(items.len());

for item in items {
    match transformation_that_may_fail(item) {
        Ok(val) => processed_items.push(val),
        Err(_) => error_count += 1,
    }
}
```

The [`match`](https://doc.rust-lang.org/std/keyword.match.html) says it all: success goes in the vector, failure bumps the counter. One pass, no closure holding a mutable borrow, and the vector is sized up front (the chain can't do that, because [`filter_map`](https://doc.rust-lang.org/std/iter/trait.Iterator.html#method.filter_map) can't know how many items will survive). I compiled both and they give the same result. Only one of them takes no effort to read.

This is Rust, not Java. Long `.stream().map().filter().collect()` pipelines are a Java habit, where chaining everything is often treated as the modern, grown-up style, and the habit travels to Rust intact. It doesn't need to. Iterator chains are not a badge of seniority, and a [`for`](https://doc.rust-lang.org/std/keyword.for.html) loop is not an admission of defeat. Rust has [`match`](https://doc.rust-lang.org/std/keyword.match.html), has loops that usually compile to the same machine code as the equivalent adapters, and has a borrow checker that makes the mutable state in a loop safe. A loop is not the "imperative fallback" here; it is often the clearest thing you can write.

To be fair to the guide, it does not ban combinators. It says to avoid *long and complex* chains, to avoid building a chain in the header of a [`for`](https://doc.rust-lang.org/std/keyword.for.html) loop (assign it to a well-named variable first), and to avoid [`for_each`](https://doc.rust-lang.org/std/iter/trait.Iterator.html#method.for_each) unless you have a good reason. It prefers combinators when they are short or when the adapter carries real logic. Its example:

```rust
let threshold_exceeded = values.iter().any(|&v| v > threshold);
```

is better than the five-line loop that rebuilds [`any()`](https://doc.rust-lang.org/std/iter/trait.Iterator.html#method.any) by hand. The rule is not "loops good, chains bad". It is: write whichever one a reader understands first.

## ✨ BeautifulRust

[BeautifulRust](https://github.com/morganlinton/BeautifulRust) by *Morgan Linton* 🏆 is a Claude Code plugin with a single skill, `rust-best-practices`, that teaches Claude to write idiomatic, robust Rust. It distils the Google guide together with the [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/), David Drysdale's [Effective Rust](https://www.lurklurk.org/effective-rust/), [Rust Design Patterns](https://rust-unofficial.github.io/patterns/) and Microsoft's [Pragmatic Rust Guidelines](https://microsoft.github.io/rust-guidelines/). Where the sources disagree, it picks a side and says why. It loads on its own whenever a task touches Rust, [`cargo`](https://doc.rust-lang.org/cargo/) or `.rs` files, and it ships with evals: in the author's last comparison, Claude passed 29 of 30 checks with the skill and 24 of 30 without it.

I have it installed. If you write Rust with an AI assistant, it is an easy way to get "just write the loop" applied without having to ask.

```bash
claude plugin marketplace add morganlinton/BeautifulRust
claude plugin install beautiful-rust@beautiful-rust
```

Or from inside a Claude Code session, run `/plugin marketplace add morganlinton/BeautifulRust`, then `/plugin install beautiful-rust@beautiful-rust`.

Even if you never use it, the five sources it draws from make a good reading list.

## 📚 Sources

- [Google Rust Style Guide](https://google.github.io/styleguide/rustguide.html), especially "Don't use iterator combinator chains when direct iteration is clearer"
- [BeautifulRust](https://github.com/morganlinton/BeautifulRust) (MIT)
- [Clippy: `manual_inspect`](https://rust-lang.github.io/rust-clippy/master/index.html#manual_inspect)
- [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/) · [Effective Rust](https://www.lurklurk.org/effective-rust/) · [Rust Design Patterns](https://rust-unofficial.github.io/patterns/) · [Microsoft Pragmatic Rust Guidelines](https://microsoft.github.io/rust-guidelines/)
