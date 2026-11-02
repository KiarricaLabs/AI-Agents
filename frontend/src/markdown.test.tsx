import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, it, expect } from "vitest";
import { Markdown } from "./markdown";

describe("Markdown renderer", () => {
  it("renders headings at the correct level", () => {
    render(<Markdown source={"# One\n\n## Two\n\n### Three"} />);
    expect(screen.getByRole("heading", { level: 1, name: "One" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Two" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Three" })).toBeInTheDocument();
  });

  it("renders paragraphs and preserves spacing between blocks", () => {
    render(<Markdown source={"first paragraph\n\nsecond paragraph"} />);
    expect(screen.getByText("first paragraph")).toBeInTheDocument();
    expect(screen.getByText("second paragraph")).toBeInTheDocument();
  });

  it("renders bold and italic inline text", () => {
    render(<Markdown source={"this is **bold** and *italic*"} />);
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText("italic").tagName).toBe("EM");
  });

  it("renders unordered and ordered lists", () => {
    render(<Markdown source={"- a\n- b\n\n1. one\n2. two"} />);
    const lists = screen.getAllByRole("list");
    expect(lists).toHaveLength(2);
    expect(lists[0].tagName).toBe("UL");
    expect(lists[1].tagName).toBe("OL");
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
  });

  it("renders blockquotes", () => {
    render(<Markdown source={"> quoted line"} />);
    const quote = screen.getByText("quoted line").closest("blockquote");
    expect(quote).toBeInTheDocument();
  });

  it("renders inline code and fenced code blocks", () => {
    render(<Markdown source={"use `x` here\n\n```ts\nconst x = 1;\n```"} />);
    expect(screen.getByText("x").tagName).toBe("CODE");
    const block = screen.getByText(/const x = 1/);
    expect(block.closest("pre")).toBeInTheDocument();
  });

  it("renders a table from GFM pipe syntax", () => {
    render(<Markdown source={"| Name | Value |\n| --- | --- |\n| a | 1 |\n| b | 2 |"} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "1" })).toBeInTheDocument();
  });

  it("renders safe links and blocks javascript: URLs", () => {
    render(
      <Markdown
        source={"[good](https://example.com) [bad](javascript:alert(1)) [data](data:text/html,x)"}
      />
    );
    const good = screen.getByText("good").closest("a");
    expect(good?.getAttribute("href")).toBe("https://example.com");
    const bad = screen.getByText("bad").closest("a");
    expect(bad?.getAttribute("href")).not.toMatch(/javascript/i);
    const data = screen.getByText("data").closest("a");
    expect(data?.getAttribute("href")).not.toMatch(/^data:/i);
  });

  it("does not execute raw HTML or scripts in the source", () => {
    const { container } = render(
      <Markdown source={'<script>alert("xss")</script><img src=x onerror=alert(1)>'} />
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    // The literal text is still present, inert, as escaped text content.
    expect(container.textContent).toContain("<script>");
  });

  it("renders plain text without markdown as a single paragraph", () => {
    render(<Markdown source={"Just some plain prose."} />);
    expect(screen.getByText("Just some plain prose.").tagName).toBe("P");
  });
});
