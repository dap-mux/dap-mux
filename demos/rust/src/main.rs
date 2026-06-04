// Dijkstra's shortest path demo for dap-mux + codelldb + dap-observer.
//
// Good breakpoint targets:
//   - Top of `shortest_path`: watch dist/prev/heap initialize
//   - The `heap.pop()` line: step iteration by iteration, watch dist grow
//   - The `if node == goal` branch: see the path reconstruction
//   - The inner `for (next, weight)` loop: watch relaxation happen

use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap};

#[derive(Debug)]
struct Graph {
    edges: HashMap<&'static str, Vec<(&'static str, u32)>>,
}

impl Graph {
    fn new() -> Self {
        Graph {
            edges: HashMap::new(),
        }
    }

    fn add_edge(&mut self, from: &'static str, to: &'static str, weight: u32) {
        self.edges.entry(from).or_default().push((to, weight));
        self.edges.entry(to).or_default().push((from, weight));
    }

    fn shortest_path<'a>(
        &'a self,
        start: &'a str,
        goal: &'a str,
    ) -> Option<(u32, Vec<&'a str>)> {
        let mut dist: HashMap<&str, u32> = HashMap::new();
        let mut prev: HashMap<&str, &str> = HashMap::new();
        let mut heap: BinaryHeap<Reverse<(u32, &str)>> = BinaryHeap::new();

        dist.insert(start, 0);
        heap.push(Reverse((0, start)));

        while let Some(Reverse((cost, node))) = heap.pop() {
            if node == goal {
                let mut path = vec![goal];
                let mut current = goal;
                while let Some(&p) = prev.get(current) {
                    path.push(p);
                    current = p;
                }
                path.reverse();
                return Some((cost, path));
            }

            if cost > *dist.get(node).unwrap_or(&u32::MAX) {
                continue;
            }

            if let Some(neighbors) = self.edges.get(node) {
                for &(next, weight) in neighbors {
                    let next_cost = cost + weight;
                    if next_cost < *dist.get(next).unwrap_or(&u32::MAX) {
                        dist.insert(next, next_cost);
                        prev.insert(next, node);
                        heap.push(Reverse((next_cost, next)));
                    }
                }
            }
        }

        None
    }
}

fn main() {
    let mut graph = Graph::new();

    //        4       5
    //   A ────── B ────── D
    //   │  \   / │         \  6
    //   2   \ /  1    8     F
    //   │    X   │   /    /
    //   C ────── + ──── E ── 3
    //       (C─D=8, C─E=10, D─E=2)

    graph.add_edge("A", "B", 4);
    graph.add_edge("A", "C", 2);
    graph.add_edge("B", "C", 1);
    graph.add_edge("B", "D", 5);
    graph.add_edge("C", "D", 8);
    graph.add_edge("C", "E", 10);
    graph.add_edge("D", "E", 2);
    graph.add_edge("D", "F", 6);
    graph.add_edge("E", "F", 3);

    let queries = [("A", "F"), ("A", "E"), ("B", "F"), ("C", "F")];

    for (start, goal) in &queries {
        match graph.shortest_path(start, goal) {
            Some((cost, path)) => {
                println!("{} → {}: cost={} path={}", start, goal, cost, path.join(" → "))
            }
            None => println!("{} → {}: no path found", start, goal),
        }
    }
}
